/* Synthetic module metadata only; no game bytes and no executable payload. */
#include "../loader_validate.h"
#include <assert.h>

static uint8_t image[0x14000];
static module_t fresh(void) {
    module_t m = {0}; m.base = image; m.size = sizeof image;
    m.text_end = 0x1000; m.ro_off = 0x4000; m.data_off = 0x8000;
    m.key_page_off = 0xc000; m.key_page_size = 0x4000; m.patch_off = 0x10000;
    for (unsigned i = 0; i < 8; i++) m.key_idx[i] = i;
    memset(image, 0, sizeof image);
    uint32_t mod = 0x4000, dyn = 0x100;
    memcpy(image + 4, &mod, 4); memcpy(image + mod, "MOD0", 4); memcpy(image + mod + 4, &dyn, 4);
    Elf64_Dyn ds[] = {{DT_SYMTAB, {.d_val=0x4400}}, {DT_STRTAB, {.d_val=0x4430}},
                     {10, {.d_val=16}}, {DT_RELA, {.d_val=0x4500}},
                     {DT_RELASZ, {.d_val=24}}, {DT_INIT, {.d_val=0x100}}, {0, {.d_val=0}}};
    memcpy(image + 0x4100, ds, sizeof ds);
    Elf64_Sym symbol = {.st_name=1, .st_shndx=1, .st_value=0x100, .st_size=4};
    memcpy(image + 0x4418, &symbol, sizeof symbol); memcpy(image + 0x4430, "\0synthetic\0", 11);
    Elf64_Rela r = {.r_offset=0x8000, .r_info=R_AARCH64_RELATIVE, .r_addend=0x100};
    memcpy(image + 0x4500, &r, sizeof r);
    return m;
}
static void u64(size_t off, uint64_t n) { memcpy(image + off, &n, 8); }
static void u32(size_t off, uint32_t n) { memcpy(image + off, &n, 4); }
#define BAD(label, expression) do { m = fresh(); expression; assert(g2m_dynamic_validate(&m) != NULL); count++; } while (0)
int main(void) {
    unsigned count = 0;
    module_t m = fresh();
    assert(g2m_layout_validate(&m, 0x3fff) == NULL);
    assert(g2m_dynamic_validate(&m) == NULL && m.nsym == 2); count++;
    assert(!g2m_span(UINT64_MAX, UINT64_MAX-2, 4));
    assert(g2m_span(8, 8, 0) && !g2m_span(8, 9, 0)); count++;
    BAD("short image", m.size = 7);
    BAD("MOD0 offset", u32(4, UINT32_MAX));
    BAD("negative dynamic", u32(0x4004, 0x80000000u));
    BAD("unaligned dynamic", u32(0x4004, 0x101));
    BAD("symbol offset", u64(0x4108, UINT64_MAX));
    BAD("string table size", u64(0x4128, UINT64_MAX));
    BAD("unaligned symbol table", u64(0x4108, 0x4401));
    BAD("bad name", u32(0x4418, 0xffffffffu));
    BAD("unterminated string", memset(image + 0x4430, 'x', 16));
    BAD("symbol value outside image", u64(0x4420, UINT64_MAX));
    BAD("symbol length overflow", u64(0x4428, UINT64_MAX));
    BAD("relocation length", u64(0x4148, 25));
    BAD("relocation offset", u64(0x4138, UINT64_MAX));
    BAD("write to executable text", u64(0x4500, 0x100));
    BAD("write to key page", u64(0x4500, 0xc000));
    BAD("write overflow", u64(0x4500, UINT64_MAX));
    BAD("unknown relocation kind", u64(0x4508, 1030));
    BAD("RELATIVE with symbol", u64(0x4508, (UINT64_C(1)<<32)|R_AARCH64_RELATIVE));
    BAD("bad symbol index", u64(0x4508, (UINT64_C(2)<<32)|R_AARCH64_ABS64));
    BAD("metadata overwritten", u64(0x4500, 0x4108));
    BAD("duplicate tag", u64(0x4120, DT_STRTAB));
    BAD("init offset", u64(0x4158, UINT64_MAX));
    m = fresh(); u64(0x4508, (UINT64_C(1)<<32)|R_AARCH64_ABS64);
    assert(g2m_dynamic_validate(&m) == NULL); count++;
    m = fresh(); memmove(image + 0x4438, image + 0x4430, 16); u64(0x4118, 0x4438);
    assert(g2m_dynamic_validate(&m) == NULL && m.nsym == 2); count++;
    m = fresh(); unsigned seen = 0;
    assert(g2m_layout_line(&m, "# KEY_K18_IDX 0\n", &seen) == NULL);
    assert(g2m_layout_line(&m, "# KEY_K18_IDX\t1\n", &seen) != NULL);
    seen = 0;
    assert(g2m_layout_line(&m, "# KEY_K18_IDX\t2048\n", &seen) != NULL);
    assert(g2m_layout_line(&m, "# KEY_K18_IDX\t-1\n", &seen) != NULL);
    assert(g2m_layout_line(&m, "# PATCH_OFF\t18446744073709551616\n", &seen) != NULL);
    assert(g2m_layout_line(&m, "# PATCH_OFF\t0x10000 junk\n", &seen) != NULL);
    assert(g2m_layout_line(&m, "# UNKNOWN\t0\n", &seen) != NULL); count += 7;
    m = fresh(); m.key_idx[7] = m.key_idx[6]; assert(g2m_layout_validate(&m, 0x3fff));
    m = fresh(); m.key_page_off = UINT64_MAX - 0x3fff; assert(g2m_layout_validate(&m, 0x3fff));
    m = fresh(); m.text_end = UINT64_MAX; assert(g2m_layout_validate(&m, 0x3fff));
    m = fresh(); assert(g2m_layout_validate(&m, 0x1fff)); count += 4;
    m = fresh(); uint64_t ret, orig; int arg; char kind[16];
    assert(!g2m_gate_line(&m, "0x10004 svc 128 0x100\n", &ret, kind, &arg, &orig));
    assert(ret == 0x10004 && arg == 128 && orig == 0x100);
    const char *invalid_gates[] = {
        "0x10004 cntpct 31 0x100", "0x10004 cntvct 999999999999999999999999999 0x100",
        "0x10004 obs 0 0x100", "0x10004 svc -1 0x100", "0x10004 bad 0 0x100",
        "0x10004 svc 0 0x100 trailing", "0x4000 svc 0 0x100", "0x10004 svc 0 0x1000",
        "0x10004 svc 0 0x101", "0x14000 svc 0 0x100", "0x10004 svc 65536 0x100"
    };
    for (unsigned i = 0; i < sizeof invalid_gates / sizeof invalid_gates[0]; i++) {
        assert(g2m_gate_line(&m, invalid_gates[i], &ret, kind, &arg, &orig)); count++;
    }
    /* A bounded mutation corpus also runs under ASan/UBSan in CI. */
    uint32_t seed = 0x12345678;
    m = fresh();
    for (unsigned i = 0; i < 5000; i++) {
        seed = seed * 1664525u + 1013904223u;
        size_t off = seed % 0x4600;
        uint8_t old = image[off]; image[off] ^= (uint8_t)(1 + seed % 255);
        (void)g2m_dynamic_validate(&m); image[off] = old;
    }
    printf("loader metadata: %u checks and 5000 bounded mutations passed\n", count);
    return 0;
}
