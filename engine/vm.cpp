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
//   +-REGLU_CLAMP=1e6) -> [erase slots] -> residual -> tanh(x/C)*C (C=1e9);
//   output = head(x), whose rows are identity projections onto the output
//   persist dims' slots.
//
// Incremental form: with K/V cached per layer at append time, a new token
// is run through the layers alone — past rows evolve after their K/V is
// cached but nothing ever reads them again, so this is exact.
//
// Usage:
//   vm_run <weights.bin|.sbin> <stream.txt> <term_pos> [max_steps=2000]
// stream.txt: first line n, then n lines "K V0 V1 V2 X E2 F2" (the stream
// BEFORE init_state; the engine appends the initial STATE token itself).
// Output: the final stream (same format), then
//   DONE <result_pos> <env_pos> <steps> | NOT_DONE <steps>
//
// Weights file: either the legacy dense format (save_weights) or the CSR
// sparse "L4SV" format (save_weights_sparse, compiler/weights.py), chosen
// by magic. The sparse file is mmapped and parsed in place — load is
// milliseconds instead of a full multi-GB read.
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <unordered_map>
#include <vector>

#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

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
    vector<int> layer_heads;  // H_li per layer (v2); global n_heads if v1
    vector<string> tokens;
    vector<vector<double>> q, k, v, out_w;  // CompactAttention (H*2, D)/(D, H*2)
    vector<vector<double>> ff_in, ff_out;   // (2F, D), (D, F)
    vector<double> head;  // (vocab, D)
    vector<vector<int>> attn_erase, ffn_erase;
    // CSR mirrors built after load; dense originals released
    vector<CSR> cq, ck, cv, cout_w, cff_in, cff_out;
    CSR chead;
    bool pre_csr = false;  // sparse file: CSR mirrors filled by the loader
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

struct FileRd {
    FILE* f;
    int32_t i32() { int32_t v; if (fread(&v, 4, 1, f) != 1) { fprintf(stderr, "bad file\n"); exit(1); } return v; }
    string name() {
        int32_t len = i32();
        string s(len, '\0');
        if (len && fread(s.data(), 1, (size_t)len, f) != (size_t)len) { fprintf(stderr, "bad file (name)\n"); exit(1); }
        return s;
    }
};

// Legacy dense loader kept as a fallback for old step_vm.bin files; the
// erase/tiebreak/meta tail is shared with the sparse loader above (the
// dense path reads the head matrix, then hands off to load_tail).

template <typename Read>
static void load_tail(Weights& w, Read&& rd) {
    int has_erase = rd.i32();
    w.attn_erase.resize(w.n_layers);
    w.ffn_erase.resize(w.n_layers);
    if (has_erase) {
        for (int li = 0; li < w.n_layers; ++li) {
            int n = rd.i32();
            for (int i = 0; i < n; ++i) w.attn_erase[li].push_back(rd.i32());
            n = rd.i32();
            for (int i = 0; i < n; ++i) w.ffn_erase[li].push_back(rd.i32());
        }
    }
    int has_tb = rd.i32();
    if (has_tb) {
        for (int i = 0; i < w.n_layers * w.n_heads; ++i) rd.i32();
    }
    int has_meta = rd.i32();
    if (has_meta) {
        int n = rd.i32();
        for (int i = 0; i < n; ++i) {
            string name = rd.name();
            int slot = rd.i32();
            w.field_slots[name] = slot;
        }
        w.one_slot = rd.i32();
        n = rd.i32();
        for (int i = 0; i < n; ++i) {
            string name = rd.name();
            int idx = rd.i32();
            w.output_index[name] = idx;
        }
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
    FileRd rd{f};
    load_tail(w, rd);
    fclose(f);
    return w;
}

// ── Sparse "L4SV" loader (mmapped, zero full-file read) ─────────────────

struct Cursor {
    const uint8_t* p;
    const uint8_t* end;

    void take(void* dst, size_t n) {
        if ((size_t)(end - p) < n) { fprintf(stderr, "sparse file truncated\n"); exit(1); }
        memcpy(dst, p, n);
        p += n;
    }
    int32_t i32() { int32_t v; take(&v, 4); return v; }
    int64_t i64() { int64_t v; take(&v, 8); return v; }
    string name() {
        int32_t len = i32();
        string s(len, '\0');
        take(s.data(), (size_t)len);
        return s;
    }
    CSR csr() {
        CSR m;
        m.rows = i32();
        int32_t cols = i32();
        int64_t nnz = i64();
        m.ptr.resize((size_t)m.rows + 1);
        take(m.ptr.data(), (size_t)(m.rows + 1) * 8);
        m.col.resize((size_t)nnz);
        take(m.col.data(), (size_t)nnz * 4);
        m.val.resize((size_t)nnz);
        take(m.val.data(), (size_t)nnz * 8);
        (void)cols;
        return m;
    }
};

// Reads erase / tiebreak / runner-meta tail — identical encoding in both
// the dense and sparse formats. `rd` abstracts FILE* vs mmapped cursor.
Weights load_weights_sparse(const char* path) {
    int fd = open(path, O_RDONLY);
    if (fd < 0) { fprintf(stderr, "cannot open %s\n", path); exit(1); }
    struct stat st;
    if (fstat(fd, &st) != 0) { fprintf(stderr, "fstat failed\n"); exit(1); }
    size_t len = (size_t)st.st_size;
    void* map = mmap(nullptr, len, PROT_READ, MAP_PRIVATE, fd, 0);
    if (map == MAP_FAILED) { fprintf(stderr, "mmap failed\n"); exit(1); }
    close(fd);
    madvise(map, len, MADV_WILLNEED);

    Cursor c{(const uint8_t*)map, (const uint8_t*)map + len};
    char magic[4];
    c.take(magic, 4);
    if (memcmp(magic, "L4SV", 4) != 0) { fprintf(stderr, "bad magic\n"); exit(1); }
    int32_t version = c.i32();
    if (version != 1 && version != 2) {
        fprintf(stderr, "unsupported L4SV version %d\n", version); exit(1);
    }

    Weights w;
    w.pre_csr = true;
    int32_t hdr[6];
    c.take(hdr, 24);
    w.vocab = hdr[0]; w.d_model = hdr[1]; w.n_layers = hdr[2];
    w.n_heads = hdr[3]; w.d_ffn = hdr[4]; w.stop_token_id = hdr[5];
    // v2: per-layer head counts (H_li), read right after the header.  Each
    // layer's q/k/v then have 2*H_li rows (out has 2*H_li cols); v1 keeps
    // the global n_heads shape.
    if (version == 2) {
        w.layer_heads.resize(w.n_layers);
        for (int i = 0; i < w.n_layers; ++i) w.layer_heads[i] = c.i32();
    }
    for (int i = 0; i < w.vocab; ++i) w.tokens.push_back(c.name());
    // embedding omitted from the sparse format (engine never reads it)
    w.cq.resize(w.n_layers); w.ck.resize(w.n_layers); w.cv.resize(w.n_layers);
    w.cout_w.resize(w.n_layers); w.cff_in.resize(w.n_layers);
    w.cff_out.resize(w.n_layers);
    for (int li = 0; li < w.n_layers; ++li) {
        w.cq[li] = c.csr();       // (H2, D)
        w.ck[li] = c.csr();
        w.cv[li] = c.csr();
        w.cout_w[li] = c.csr();   // (D, H2)
        w.cff_in[li] = c.csr();   // (2F, D)
        w.cff_out[li] = c.csr();  // (D, F)
    }
    w.chead = c.csr();            // (vocab, D)
    load_tail(w, c);
    munmap(map, len);
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
        fprintf(stderr, "usage: vm_run <weights.bin|.sbin> <stream.txt> <term_pos> [max_steps]\n");
        return 2;
    }
    Weights W;
    {
        FILE* probe = fopen(argv[1], "rb");
        if (!probe) { fprintf(stderr, "cannot open %s\n", argv[1]); exit(1); }
        char magic[4] = {0, 0, 0, 0};
        if (fread(magic, 1, 4, probe) != 4) { fprintf(stderr, "bad weights file\n"); exit(1); }
        fclose(probe);
        W = (memcmp(magic, "L4SV", 4) == 0) ? load_weights_sparse(argv[1])
                                            : load_weights(argv[1]);
    }
    const int D = W.d_model, H = W.n_heads, F = W.d_ffn;
    // v1 / dense fallback: uniform global head count.  v2 sparse sets H_li
    // per layer (0 for the 65 lookup-free layers).
    if ((int)W.layer_heads.size() != W.n_layers)
        W.layer_heads.assign(W.n_layers, H);
    if (!W.pre_csr) {
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
    // ReGLU output clamp — same semantic as compiler/weights.py's
    // REGLU_CLAMP (model/runner.py imports that one); this file is the C++
    // mirror, keep in sync by hand. 1e6 ≤ 2^24-1 keeps integer readouts
    // exact under fp32 storage + llround, and it exceeds every legal stream
    // position: the step loop below emits ≤ 10 tokens/step (9 conditional
    // emission arms + STATE) and the verify harness budget is 3000 steps
    // (scripts/verify_engine_vs_refvm.py max_steps), so stream ≤ n0+30001;
    // largest legal F read observed is 1003 (pow, 1203-token stream). The
    // old 1000 flattened that read to exactly 1000.0 and desynced the
    // machine — docs/handoffs/002-C-wp6.md C5 step 1.6, docs/decisions/013.
    const double REGLU_CLAMP = 1e6;
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
              I_FRAME_X = need(W.output_index, "frame_X"),
              I_FRAME_E2 = need(W.output_index, "frame_E2"),
              I_FRAME_F2 = need(W.output_index, "frame_F2");
    const int I_F2_TASK = need(W.output_index, "frame2_task"),
              I_F2_V1 = need(W.output_index, "frame2_V1"),
              I_F2_V2 = need(W.output_index, "frame2_V2"),
              I_F2_X = need(W.output_index, "frame2_X"),
              I_F2_E2 = need(W.output_index, "frame2_E2"),
              I_F2_F2 = need(W.output_index, "frame2_F2");
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
    // H3: exact argmax is the DEFAULT winner selection (a lookup is a
    // discrete fetch; argmax is scale-invariant and needs no HARD_K
    // temperature).  VM_SOFTMAX=1 restores the old saturating-softmax path
    // for A/B comparison; VM_HARDMAX is kept as a legacy alias.
    const bool softmax = getenv("VM_SOFTMAX") != nullptr;
    const bool hardmax = !softmax || getenv("VM_HARDMAX") != nullptr;
    vector<double> row(D);
    vector<double> last_residual;  // final residual row of the newest position
    long long T = 0;  // number of processed positions
    auto append_pos = [&](const Tok& t) {
        row = make_row(t, T);
        vector<double> x = row;
        for (int li = 0; li < W.n_layers; ++li) {
            for (int s : W.attn_erase[li]) x[s] = 0.0;
            // H2/H3: per-layer head count.  h_l == 0 (65 of 99 layers) means
            // the layer carries no LookUp: its q/k/v/out matrices are empty,
            // so the whole routing sublayer is skipped (the FFN still runs).
            const int h_l = W.layer_heads[li];
            if (h_l > 0) {
                const int H2l = h_l * 2;
                vector<double> qv(H2l), kv(H2l), vv(H2l);
                spmv(W.cq[li], x, qv);
                spmv(W.ck[li], x, kv);
                spmv(W.cv[li], x, vv);
                const size_t base = (size_t)T * H2l;
                kc[li].resize(base + H2l);
                vc[li].resize(base + H2l);
                for (int i = 0; i < H2l; ++i) { kc[li][base + i] = kv[i]; vc[li][base + i] = vv[i]; }

                vector<double> attn_out(H2l, 0.0);
                for (int h = 0; h < h_l; ++h) {
                    const double qx = qv[h*2], qy = qv[h*2+1];
                    // Winner selection.  Default: exact argmax — a lookup is
                    // a discrete fetch, and every lookup's key carries the
                    // inv_log_pos tie-break term (no true ties), so argmax is
                    // bit-identical to the saturating softmax but needs no
                    // temperature and cannot overflow fp16.  VM_SOFTMAX
                    // restores the softmax path for A/B comparison.
                    vector<double> sc(T + 1);
                    double best = -1e300;
                    for (long long u = 0; u <= T; ++u) {
                        double s = qx * kc[li][(size_t)u*H2l + h*2]
                                 + qy * kc[li][(size_t)u*H2l + h*2 + 1];
                        s /= SCALE;
                        sc[u] = s;
                        if (s > best) best = s;
                    }
                    if (hardmax) {
                        long long w = 0;
                        for (long long u = 1; u <= T; ++u) if (sc[u] > sc[w]) w = u;
                        attn_out[h*2] = vc[li][(size_t)w*H2l + h*2];
                        attn_out[h*2+1] = vc[li][(size_t)w*H2l + h*2 + 1];
                    } else {
                    double Z = 0.0;
                    for (long long u = 0; u <= T; ++u) { sc[u] = std::exp(sc[u] - best); Z += sc[u]; }
                    double ox = 0.0, oy = 0.0;
                    for (long long u = 0; u <= T; ++u) {
                        const double p = sc[u] / Z;
                        ox += p * vc[li][(size_t)u*H2l + h*2];
                        oy += p * vc[li][(size_t)u*H2l + h*2 + 1];
                    }
                    attn_out[h*2] = ox; attn_out[h*2+1] = oy;
                    }
                }
                vector<double> ao(D);
                spmv(W.cout_w[li], attn_out, ao);
                for (int i = 0; i < D; ++i) x[i] += ao[i];
            }

            vector<double> go(2 * F);
            spmv(W.cff_in[li], x, go);
            for (int s : W.ffn_erase[li]) x[s] = 0.0;
            vector<double> act(F);
            for (int j = 0; j < F; ++j) {
                double a = std::max(0.0, go[j]) * go[F + j];
                if (a > REGLU_CLAMP) a = REGLU_CLAMP;
                else if (a < -REGLU_CLAMP) a = -REGLU_CLAMP;
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
        if (rd(I_EFRAME)) emit(T_FRAME, rd(I_FRAME_TASK), rd(I_FRAME_V1), rd(I_FRAME_V2), rd(I_FRAME_X), rd(I_FRAME_E2), rd(I_FRAME_F2));
        if (rd(I_EFRAME2)) emit(T_FRAME, rd(I_F2_TASK), rd(I_F2_V1), rd(I_F2_V2), rd(I_F2_X), rd(I_F2_E2), rd(I_F2_F2));
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
