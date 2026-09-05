// vm.cpp — Phase 4 C++17 inference engine for the compiled Lean-kernel VM.
//
// Loads the analytic weights exported by compiler/weights.py (binary format,
// see save_weights), runs the autoregressive micro-step loop of VM_SPEC
// §10.3 (the model/runner.py WeightRunner contract) with an incremental
// KV cache, and prints the final token stream + result closure.
//
// Math contract (must match LeanTransformer.forward_stream exactly):
//   residual row per position = 7 token-field slots + one=1.0, and the
//   position builtins (slots 1/2/3 = pos, inv_log_pos, pos^2) added once
//   before layer 0;
//   per layer: [erase slots] -> causal attention (d_head=2, softmax with
//   scale 1/sqrt(2); weights built at HARD_K=1e4 make it a hardmax) ->
//   residual -> ReGLU FFN (chunks gate|val; act=relu(gate)*val; clamp
//   +-1000) -> [erase slots] -> residual -> tanh(x/C)*C (C=1e9);
//   output = head(x), whose rows are identity projections onto the output
//   persist dims' slots.
//
// Incremental form: with K/V cached per layer at append time, a new token
// is run through the layers alone — past rows evolve after their K/V is
// cached but nothing ever reads them again, so this is exact.
//
// Usage:
//   vm_run <weights.bin> <stream.txt> <term_pos> [max_steps=2000]
// stream.txt: first line n, then n lines "K V0 V1 V2 X E2 F2" (the stream
// BEFORE init_state; the engine appends the initial STATE token itself).
// Output: the final stream (same format), then
//   DONE <result_pos> <env_pos> <steps> | NOT_DONE <steps>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <unordered_map>
#include <vector>

using std::string;
using std::vector;

namespace {

// CSR sparse matrix. The analytic construction leaves every weight row with
// a handful of nonzeros, so a dense matvec is memory-bandwidth-bound on the
// full 151 MB weight file; skipping exact zeros is bit-exact for finite
// values (0.0 terms contribute nothing to the IEEE sum).
struct CSR {
    vector<double> val;
    vector<int> col;
    vector<long long> ptr;  // rows+1
    int rows = 0;
};

CSR to_csr(const vector<double>& W, int rows, int ld) {
    CSR m;
    m.rows = rows;
    m.ptr.assign(rows + 1, 0);
    for (int i = 0; i < rows; ++i) {
        long long n = 0;
        for (int j = 0; j < ld; ++j)
            if (W[(size_t)i * ld + j] != 0.0) ++n;
        m.ptr[i + 1] = m.ptr[i] + n;
    }
    m.val.resize(m.ptr[rows]);
    m.col.resize(m.ptr[rows]);
    for (int i = 0; i < rows; ++i) {
        long long p = m.ptr[i];
        for (int j = 0; j < ld; ++j) {
            double w = W[(size_t)i * ld + j];
            if (w != 0.0) { m.val[p] = w; m.col[p] = j; ++p; }
        }
    }
    return m;
}

void spmv(const CSR& m, const vector<double>& x, vector<double>& y) {
    for (int i = 0; i < m.rows; ++i) {
        double s = 0.0;
        for (long long p = m.ptr[i]; p < m.ptr[i + 1]; ++p)
            s += m.val[p] * x[m.col[p]];
        y[i] = s;
    }
}


struct Weights {
    int vocab, d_model, n_layers, n_heads, d_ffn, stop_token_id;
    vector<string> tokens;
    vector<vector<double>> q, k, v, out_w;  // CompactAttention (H*2, D)/(D, H*2)
    vector<vector<double>> ff_in, ff_out;   // (2F, D), (D, F)
    vector<double> head;  // (vocab, D)
    vector<vector<int>> attn_erase, ffn_erase;
    // CSR mirrors built after load; dense originals released
    vector<CSR> cq, ck, cv, cout_w, cff_in, cff_out;
    CSR chead;
    std::unordered_map<string, int> field_slots, output_index;
    int one_slot = -1;
};

string read_name(FILE* f) {
    int len = 0;
    if (fread(&len, 4, 1, f) != 1) { fprintf(stderr, "bad file (name len)\n"); exit(1); }
    string s(len, '\0');
    if (len && fread(s.data(), 1, len, f) != (size_t)len) {
        fprintf(stderr, "bad file (name)\n"); exit(1);
    }
    return s;
}

vector<double> read_mat(FILE* f, size_t n) {
    vector<double> m(n);
    if (fread(m.data(), sizeof(double), n, f) != n) {
        fprintf(stderr, "bad file (matrix)\n"); exit(1);
    }
    return m;
}

void skip(FILE* f, size_t n) {
    if (fseek(f, (long)(n * sizeof(double)), SEEK_CUR) != 0) {
        fprintf(stderr, "bad file (seek)\n"); exit(1);
    }
}

Weights load_weights(const char* path) {
    FILE* f = fopen(path, "rb");
    if (!f) { fprintf(stderr, "cannot open %s\n", path); exit(1); }
    Weights w;
    int hdr[6];
    if (fread(hdr, 4, 6, f) != 6) { fprintf(stderr, "bad header\n"); exit(1); }
    w.vocab = hdr[0]; w.d_model = hdr[1]; w.n_layers = hdr[2];
    w.n_heads = hdr[3]; w.d_ffn = hdr[4]; w.stop_token_id = hdr[5];
    for (int i = 0; i < w.vocab; ++i) w.tokens.push_back(read_name(f));
    const int D = w.d_model, H = w.n_heads, F = w.d_ffn, H2 = H * 2;
    skip(f, (size_t)w.vocab * D);  // embedding: unused (fields go straight
    // into residual slots; the vocab here is only the output-dim name table)
    w.q.resize(w.n_layers); w.k.resize(w.n_layers); w.v.resize(w.n_layers);
    w.out_w.resize(w.n_layers); w.ff_in.resize(w.n_layers); w.ff_out.resize(w.n_layers);
    for (int li = 0; li < w.n_layers; ++li) {
        w.q[li] = read_mat(f, (size_t)H2 * D);
        w.k[li] = read_mat(f, (size_t)H2 * D);
        w.v[li] = read_mat(f, (size_t)H2 * D);
        w.out_w[li] = read_mat(f, (size_t)D * H2);
        w.ff_in[li] = read_mat(f, (size_t)2 * F * D);
        w.ff_out[li] = read_mat(f, (size_t)D * F);
    }
    w.head = read_mat(f, (size_t)w.vocab * D);  // head rows: identity
    // projections onto the output dims' slots — must be APPLIED (row idx is
    // a logits dimension, not a residual slot)
    int has_erase = 0;
    if (fread(&has_erase, 4, 1, f) != 1) { fprintf(stderr, "bad file\n"); exit(1); }
    w.attn_erase.resize(w.n_layers); w.ffn_erase.resize(w.n_layers);
    if (has_erase) {
        for (int li = 0; li < w.n_layers; ++li) {
            int n = 0;
            if (fread(&n, 4, 1, f) != 1) exit(1);
            for (int i = 0; i < n; ++i) { int s; if (fread(&s, 4, 1, f) != 1) exit(1); w.attn_erase[li].push_back(s); }
            if (fread(&n, 4, 1, f) != 1) exit(1);
            for (int i = 0; i < n; ++i) { int s; if (fread(&s, 4, 1, f) != 1) exit(1); w.ffn_erase[li].push_back(s); }
        }
    }
    int has_tb = 0;
    if (fread(&has_tb, 4, 1, f) != 1) exit(1);
    if (has_tb) {
        int tb = 0;
        for (int i = 0; i < w.n_layers * w.n_heads; ++i)
            if (fread(&tb, 4, 1, f) != 1) exit(1);
    }
    int has_meta = 0;
    if (fread(&has_meta, 4, 1, f) != 1) exit(1);
    if (has_meta) {
        int n = 0;
        if (fread(&n, 4, 1, f) != 1) exit(1);
        for (int i = 0; i < n; ++i) {
            string name = read_name(f);
            int slot = 0; if (fread(&slot, 4, 1, f) != 1) exit(1);
            w.field_slots[name] = slot;
        }
        if (fread(&w.one_slot, 4, 1, f) != 1) exit(1);
        if (fread(&n, 4, 1, f) != 1) exit(1);
        for (int i = 0; i < n; ++i) {
            string name = read_name(f);
            int idx = 0; if (fread(&idx, 4, 1, f) != 1) exit(1);
            w.output_index[name] = idx;
        }
    }
    fclose(f);
    return w;
}

// y[i] = sum_j W[i*ld + j] * x[j]  (row-major)
void matvec(const vector<double>& W, int rows, int ld,
            const double* x, vector<double>& y) {
    for (int i = 0; i < rows; ++i) {
        double s = 0.0;
        const double* r = W.data() + (size_t)i * ld;
        for (int j = 0; j < ld; ++j) s += r[j] * x[j];
        y[i] = s;
    }
}

struct Tok { long long f[7]; };

}  // namespace

int main(int argc, char** argv) {
    if (argc < 4) {
        fprintf(stderr, "usage: vm_run <weights.bin> <stream.txt> <term_pos> [max_steps]\n");
        return 2;
    }
    Weights W = load_weights(argv[1]);
    const int D = W.d_model, H = W.n_heads, F = W.d_ffn;
    {
        const int H2b = H * 2;
        W.cq.resize(W.n_layers); W.ck.resize(W.n_layers); W.cv.resize(W.n_layers);
        W.cout_w.resize(W.n_layers); W.cff_in.resize(W.n_layers); W.cff_out.resize(W.n_layers);
        for (int li = 0; li < W.n_layers; ++li) {
            W.cq[li] = to_csr(W.q[li], H2b, D);
            W.ck[li] = to_csr(W.k[li], H2b, D);
            W.cv[li] = to_csr(W.v[li], H2b, D);
            W.cout_w[li] = to_csr(W.out_w[li], D, H2b);
            W.cff_in[li] = to_csr(W.ff_in[li], 2 * F, D);
            W.cff_out[li] = to_csr(W.ff_out[li], D, F);
            vector<double>().swap(W.q[li]); vector<double>().swap(W.k[li]);
            vector<double>().swap(W.v[li]); vector<double>().swap(W.out_w[li]);
            vector<double>().swap(W.ff_in[li]); vector<double>().swap(W.ff_out[li]);
        }
        W.chead = to_csr(W.head, W.vocab, D);
        vector<double>().swap(W.head);
    }
    const double TANH_C = 1e9;
    const double k1log2 = 1.0 / std::log(2.0);
    const double SCALE = std::sqrt(2.0);

    // ── initial stream (pre-init_state) ──
    FILE* sf = fopen(argv[2], "r");
    if (!sf) { fprintf(stderr, "cannot open %s\n", argv[2]); return 2; }
    int n0 = 0;
    if (fscanf(sf, "%d", &n0) != 1) { fprintf(stderr, "bad stream file\n"); return 2; }
    vector<Tok> stream(n0);
    for (int i = 0; i < n0; ++i) {
        Tok t{};
        for (int j = 0; j < 7; ++j)
            if (fscanf(sf, "%lld", &t.f[j]) != 1) { fprintf(stderr, "bad stream line %d\n", i); return 2; }
        stream[i] = t;
    }
    fclose(sf);
    long long term_pos = atoll(argv[3]);
    int max_steps = argc > 4 ? atoi(argv[4]) : 2000;

    auto need = [&](const std::unordered_map<string, int>& m,
                    const char* name) -> int {
        auto it = m.find(name);
        if (it == m.end()) { fprintf(stderr, "missing meta %s\n", name); exit(1); }
        return it->second;
    };
    const int S_K = need(W.field_slots, "k"), S_V0 = need(W.field_slots, "v0"),
              S_V1 = need(W.field_slots, "v1"), S_V2 = need(W.field_slots, "v2"),
              S_X = need(W.field_slots, "x"), S_E2 = need(W.field_slots, "e2"),
              S_F2 = need(W.field_slots, "f2");
    const int I_DONE = need(W.output_index, "done"), I_A = need(W.output_index, "A"),
              I_B = need(W.output_index, "B"), I_C = need(W.output_index, "C"),
              I_D = need(W.output_index, "D"), I_E = need(W.output_index, "E"),
              I_F = need(W.output_index, "F"), I_RPOS = need(W.output_index, "result_pos");
    const int I_EPEND = need(W.output_index, "em_pend"),
              I_ELINK = need(W.output_index, "em_link"),
              I_ELITDIG = need(W.output_index, "em_litdig"),
              I_EFRAME = need(W.output_index, "em_frame"),
              I_EFRAME2 = need(W.output_index, "em_frame2"),
              I_ELITHEAD = need(W.output_index, "em_lithead"),
              I_EGAP = need(W.output_index, "em_gap"),
              I_ELITDIG2 = need(W.output_index, "em_litdig2"),
              I_ECONST = need(W.output_index, "em_const");
    const int I_PEND_V0 = need(W.output_index, "pend_V0"),
              I_PEND_PREV = need(W.output_index, "pend_prev"),
              I_PEND_ENV = need(W.output_index, "pend_env");
    const int I_LINK_V0 = need(W.output_index, "link_V0"),
              I_LINK_V1 = need(W.output_index, "link_V1"),
              I_LINK_PREV = need(W.output_index, "link_prev"),
              I_LINK_ENV = need(W.output_index, "link_env");
    const int I_DIG_V0 = need(W.output_index, "dig_V0"),
              I_DIG2_V0 = need(W.output_index, "dig2_V0");
    const int I_FRAME_TASK = need(W.output_index, "frame_task"),
              I_FRAME_V1 = need(W.output_index, "frame_V1"),
              I_FRAME_V2 = need(W.output_index, "frame_V2"),
              I_FRAME_X = need(W.output_index, "frame_X");
    const int I_F2_TASK = need(W.output_index, "frame2_task"),
              I_F2_V1 = need(W.output_index, "frame2_V1"),
              I_F2_V2 = need(W.output_index, "frame2_V2"),
              I_F2_X = need(W.output_index, "frame2_X");
    const int I_HEAD_V0 = need(W.output_index, "head_V0"),
              I_HEAD_V2 = need(W.output_index, "head_V2"),
              I_HEAD_X = need(W.output_index, "head_X");
    const int I_CONST_CID = need(W.output_index, "const_cid");

    // Token kinds mirrored from expr/model.py + expr/tokens.py
    const long long T_PEND = 30, T_LINK = 31, T_FRAME = 32, T_STATE = 33,
                    T_LIT_DIG = 13, K_LIT = 10, K_CONST = 5, LIT_NAT = 0;

    // ── residual rows + incremental forward ──
    vector<vector<double>> kc(W.n_layers), vc(W.n_layers);  // T * H2 each
    auto make_row = [&](const Tok& t, long long pos) {
        vector<double> r(D, 0.0);
        const int slots[7] = {S_K, S_V0, S_V1, S_V2, S_X, S_E2, S_F2};
        for (int j = 0; j < 7; ++j)
            if (t.f[j]) r[slots[j]] = (double)t.f[j];
        r[W.one_slot] = 1.0;
        // position builtins (forward_stream's pos_enc), slots 1/2/3
        r[1] = (double)pos;
        r[2] = k1log2 - 1.0 / std::log((double)pos + 2.0);
        r[3] = (double)pos * (double)pos;
        return r;
    };

    const bool dbg = getenv("VM_DEBUG") != nullptr;
    const bool hardmax = getenv("VM_HARDMAX") != nullptr;
    vector<double> row(D);
    vector<double> last_residual;  // final residual row of the newest position
    long long T = 0;  // number of processed positions
    auto append_pos = [&](const Tok& t) {
        row = make_row(t, T);
        vector<double> x = row;
        const int H2 = H * 2;
        for (int li = 0; li < W.n_layers; ++li) {
            for (int s : W.attn_erase[li]) x[s] = 0.0;
            vector<double> qv(H2), kv(H2), vv(H2);
            spmv(W.cq[li], x, qv);
            spmv(W.ck[li], x, kv);
            spmv(W.cv[li], x, vv);
            const size_t base = (size_t)T * H2;
            kc[li].resize(base + H2);
            vc[li].resize(base + H2);
            for (int i = 0; i < H2; ++i) { kc[li][base + i] = kv[i]; vc[li][base + i] = vv[i]; }

            vector<double> attn_out(H2, 0.0);
            for (int h = 0; h < H; ++h) {
                const double qx = qv[h*2], qy = qv[h*2+1];
                // Winner selection. VM_HARDMAX=1 uses exact argmax —
                // mathematically identical here because every lookup's key
                // carries the inv_log_pos tie-break term (no true ties);
                // default softmax matches the Python runner's math exactly.
                vector<double> sc(T + 1);
                double best = -1e300;
                for (long long u = 0; u <= T; ++u) {
                    double s = qx * kc[li][(size_t)u*H2 + h*2]
                             + qy * kc[li][(size_t)u*H2 + h*2 + 1];
                    s /= SCALE;
                    sc[u] = s;
                    if (s > best) best = s;
                }
                if (hardmax) {
                    long long w = 0;
                    for (long long u = 1; u <= T; ++u) if (sc[u] > sc[w]) w = u;
                    attn_out[h*2] = vc[li][(size_t)w*H2 + h*2];
                    attn_out[h*2+1] = vc[li][(size_t)w*H2 + h*2 + 1];
                } else {
                double Z = 0.0;
                for (long long u = 0; u <= T; ++u) { sc[u] = std::exp(sc[u] - best); Z += sc[u]; }
                double ox = 0.0, oy = 0.0;
                for (long long u = 0; u <= T; ++u) {
                    const double p = sc[u] / Z;
                    ox += p * vc[li][(size_t)u*H2 + h*2];
                    oy += p * vc[li][(size_t)u*H2 + h*2 + 1];
                }
                attn_out[h*2] = ox; attn_out[h*2+1] = oy;
                }
            }
            vector<double> ao(D);
            spmv(W.cout_w[li], attn_out, ao);
            for (int i = 0; i < D; ++i) x[i] += ao[i];

            vector<double> go(2 * F);
            spmv(W.cff_in[li], x, go);
            for (int s : W.ffn_erase[li]) x[s] = 0.0;
            vector<double> act(F);
            for (int j = 0; j < F; ++j) {
                double a = std::max(0.0, go[j]) * go[F + j];
                if (a > 1000.0) a = 1000.0;
                else if (a < -1000.0) a = -1000.0;
                act[j] = a;
            }
            vector<double> fo(D);
            spmv(W.cff_out[li], act, fo);
            for (int i = 0; i < D; ++i) {
                const double xv = x[i] + fo[i];
                x[i] = std::tanh(xv / TANH_C) * TANH_C;
            }
        }
        ++T;
        last_residual = x;
        return x;  // final residual row of this position
    };

    // ── autoregressive micro-step loop (WeightRunner.step contract) ──
    auto emit = [&](long long K, long long V0, long long V1, long long V2,
                    long long X, long long E2, long long F2) {
        Tok t{{K, V0, V1, V2, X, E2, F2}};
        stream.push_back(t);
    };

    // init_state: STATE(A=term_pos), then forward every position once
    emit(T_STATE, term_pos, 0, 0, 0, 0, 0);
    while (T < (long long)stream.size()) append_pos(stream[T]);

    long long steps = 0;
    long long result_pos = -1, result_env = -1;
    bool done = false;
    vector<double> out(D);
    for (int s = 0; s < max_steps; ++s) {
        // last position (the STATE token) was already forwarded by the
        // tail while-loop of the previous iteration (or by init) — only
        // apply the output readout here
        out.assign(W.vocab, 0.0);
        spmv(W.chead, last_residual, out);
        if (dbg) {
            for (const auto& kv : W.output_index)
                fprintf(stderr, "OUT %s %.17g\n", kv.first.c_str(), out[kv.second]);
            fprintf(stderr, "ENDSTEP\n");
        }
        auto rd = [&](int idx) -> long long {
            return (long long)std::llround(out[idx]);
        };
        if (rd(I_DONE)) {
            done = true;
            result_pos = rd(I_RPOS);
            result_env = rd(I_B);
            break;
        }
        if (rd(I_EPEND)) emit(T_PEND, rd(I_PEND_V0), 0, rd(I_PEND_PREV), rd(I_PEND_ENV), 0, 0);
        if (rd(I_ELINK)) emit(T_LINK, rd(I_LINK_V0), rd(I_LINK_V1), rd(I_LINK_PREV), rd(I_LINK_ENV), 0, 0);
        if (rd(I_ELITDIG)) emit(T_LIT_DIG, rd(I_DIG_V0), 0, rd(I_F), 0, 0, 0);
        if (rd(I_EFRAME)) emit(T_FRAME, rd(I_FRAME_TASK), rd(I_FRAME_V1), rd(I_FRAME_V2), rd(I_FRAME_X), 0, 0);
        if (rd(I_EFRAME2)) emit(T_FRAME, rd(I_F2_TASK), rd(I_F2_V1), rd(I_F2_V2), rd(I_F2_X), 0, 0);
        if (rd(I_ELITHEAD)) emit(K_LIT, rd(I_HEAD_V0), LIT_NAT, rd(I_HEAD_V2), rd(I_HEAD_X), 0, 0);
        if (rd(I_EGAP)) emit(0, 0, 0, 0, 0, 0, 0);
        if (rd(I_ELITDIG2)) emit(T_LIT_DIG, rd(I_DIG2_V0), 0, rd(I_F), 0, 0, 0);
        if (rd(I_ECONST)) emit(K_CONST, rd(I_CONST_CID), 0, 0, 0, 0, 0);
        emit(T_STATE, rd(I_A), rd(I_B), rd(I_C), rd(I_D), rd(I_E), rd(I_F));
        steps++;
        // forward the newly appended tokens (emissions + STATE)
        while (T < (long long)stream.size()) append_pos(stream[T]);
    }

    // ── output ──
    printf("%zu\n", stream.size());
    for (const Tok& t : stream) {
        printf("%lld %lld %lld %lld %lld %lld %lld\n",
               t.f[0], t.f[1], t.f[2], t.f[3], t.f[4], t.f[5], t.f[6]);
    }
    if (done) printf("DONE %lld %lld %lld\n", result_pos, result_env, steps);
    else printf("NOT_DONE %lld\n", steps);
    return 0;
}
