/* Asset-free validation shared by the real loader and portable regressions.
 * Validate integers before pointer arithmetic. No guest bytes are executed. */
#pragma once
#include "dm.h"
#include <ctype.h>
#include <errno.h>
#include <limits.h>

static inline int g2m_span(uint64_t size, uint64_t offset, uint64_t length) {
    return offset <= size && length <= size - offset;
}

static inline const char *g2m_layout_line(module_t *m, const char *line, unsigned *seen) {
    static const char *const keys[] = {
        "PATCH_OFF", "KEY_PAGE_OFF", "KEY_PAGE_SIZE", "TEXT_END", "RO_OFF", "DATA_OFF",
        "KEY_K18_IDX", "KEY_KTLS_IDX", "KEY_KTLR_IDX", "KEY_KGATE_IDX",
        "KEY_KRES0_IDX", "KEY_KRES1_IDX", "KEY_KASPECT_IDX", "KEY_KASPECTUI_IDX"
    };
    const char *p = line;
    if (*p++ != '#') return "layout_syntax";
    if (!isspace((unsigned char)*p)) return "layout_syntax";
    while (isspace((unsigned char)*p)) p++;
    const char *begin = p;
    while (*p && !isspace((unsigned char)*p)) p++;
    size_t n = (size_t)(p - begin);
    unsigned k;
    for (k = 0; k < 14; k++) if (strlen(keys[k]) == n && !memcmp(keys[k], begin, n)) break;
    if (k == 14) return "layout_unknown_field";
    if (*seen & (1u << k)) return "layout_duplicate_field";
    while (isspace((unsigned char)*p)) p++;
    if (!isdigit((unsigned char)*p)) return "layout_number";
    errno = 0;
    char *end;
    unsigned long long value = strtoull(p, &end, k < 6 ? 0 : 10);
    if (errno == ERANGE || p == end) return "layout_number";
    while (isspace((unsigned char)*end)) end++;
    if (*end) return "layout_trailing_data";
    if (k < 6) {
        uint64_t *fields[] = {&m->patch_off, &m->key_page_off, &m->key_page_size,
                              &m->text_end, &m->ro_off, &m->data_off};
        *fields[k] = (uint64_t)value;
    } else {
        if (value >= 0x4000 / sizeof(uint64_t)) return "layout_key_index";
        m->key_idx[k - 6] = (unsigned)value;
    }
    *seen |= 1u << k;
    return NULL;
}

static inline const char *g2m_layout_validate(const module_t *m, unsigned seen) {
    if (seen != (1u << 14) - 1) return "layout_missing_field";
    if (!m->text_end || m->text_end > UINT64_MAX - 0x3fff) return "layout_text_range";
    uint64_t rx = (m->text_end + 0x3fff) & ~UINT64_C(0x3fff);
    if (m->key_page_size != 0x4000 || m->key_page_off % 0x4000 || m->patch_off % 0x4000 ||
        !g2m_span(m->patch_off, m->key_page_off, m->key_page_size) ||
        rx > m->key_page_off || m->text_end > m->ro_off || m->ro_off > m->data_off ||
        m->data_off > m->key_page_off) return "layout_segment_order";
    for (unsigned i = 0; i < 8; i++) {
        if (m->key_idx[i] >= m->key_page_size / 8) return "layout_key_index";
        for (unsigned j = 0; j < i; j++)
            if (m->key_idx[j] == m->key_idx[i]) return "layout_key_alias";
    }
    return NULL;
}

/* Validate the bounded MOD0/dynamic/symbol/rela graph before the loader walks it.
 * Only the four relocation kinds already implemented by Game2Mobile are accepted.
 * Unknown kinds are NOT reinterpreted as ABS64, nor silently skipped as TLS. */
static inline const char *g2m_dynamic_validate(module_t *m) {
    enum { V_STRSZ = 10, V_SYMENT = 11, V_RELAENT = 9, V_PLTREL = 20 };
    uint32_t mod;
    int32_t relative;
    if (!m->base || m->size < 8) return "module_too_small";
    memcpy(&mod, m->base + 4, 4);
    if (!g2m_span(m->size, mod, 8) || memcmp(m->base + mod, "MOD0", 4)) return "mod0_range";
    memcpy(&relative, m->base + mod + 4, 4);
    int64_t signed_off = (int64_t)mod + relative;
    if (signed_off < 0 || (uint64_t)signed_off % 8 ||
        !g2m_span(m->size, (uint64_t)signed_off, sizeof(Elf64_Dyn))) return "dynamic_range";
    uint64_t dynoff = (uint64_t)signed_off, ndyn = 0;
    uint64_t sym = 0, str = 0, strsz = 0, rela[2] = {0}, relasz[2] = {0};
    unsigned seen = 0;
    uint64_t sym_ent = sizeof(Elf64_Sym), rela_ent = sizeof(Elf64_Rela), plt_kind = DT_RELA;
    m->init = m->init_array = m->init_arraysz = 0;
    int terminated = 0;
    for (uint64_t at = dynoff; g2m_span(m->size, at, sizeof(Elf64_Dyn)); at += sizeof(Elf64_Dyn)) {
        Elf64_Dyn d; memcpy(&d, m->base + at, sizeof d); ndyn++;
        if (!d.d_tag) { terminated = 1; break; }
        unsigned slot = 99;
        uint64_t *target = NULL;
        switch (d.d_tag) {
        case DT_SYMTAB: slot = 0; target = &sym; break;
        case DT_STRTAB: slot = 1; target = &str; break;
        case V_STRSZ: slot = 2; target = &strsz; break;
        case V_SYMENT: slot = 3; target = &sym_ent; break;
        case DT_RELA: slot = 4; target = &rela[0]; break;
        case DT_RELASZ: slot = 5; target = &relasz[0]; break;
        case DT_JMPREL: slot = 6; target = &rela[1]; break;
        case DT_PLTRELSZ: slot = 7; target = &relasz[1]; break;
        case V_RELAENT: slot = 8; target = &rela_ent; break;
        case V_PLTREL: slot = 9; target = &plt_kind; break;
        case DT_INIT: slot = 10; target = &m->init; break;
        case DT_INIT_ARRAY: slot = 11; target = &m->init_array; break;
        case DT_INIT_ARRAYSZ: slot = 12; target = &m->init_arraysz; break;
        default: break; /* Unknown non-relocation tags retain existing behavior. */
        }
        if (target) {
            if (seen & (1u << slot)) return "dynamic_duplicate_tag";
            seen |= 1u << slot; *target = d.d_un.d_val;
        }
    }
    if (!terminated) return "dynamic_unterminated";
    if ((seen & 7) != 7 || !strsz || sym % 8 || str <= sym || str - sym < sizeof(Elf64_Sym) ||
        sym_ent != sizeof(Elf64_Sym) || !g2m_span(m->size, sym, str - sym) ||
        !g2m_span(m->size, str, strsz)) return "symbol_table_range";
    /* Keep the existing symbol-count inference, including sub-entry alignment
     * padding before the string table. Never round up into that padding. */
    uint64_t nsym = (str - sym) / sizeof(Elf64_Sym);
    if (nsym > (1u << 26)) return "symbol_table_limit";
    for (uint64_t i = 0; i < nsym; i++) {
        Elf64_Sym s; memcpy(&s, m->base + sym + i * sizeof s, sizeof s);
        if (s.st_name >= strsz || !memchr(m->base + str + s.st_name, 0, (size_t)(strsz - s.st_name)))
            return "symbol_name_range";
        if (s.st_shndx && !g2m_span(m->size, s.st_value, s.st_size)) return "symbol_value_range";
    }
    if ((m->init && (m->init % 4 || !g2m_span(m->size, m->init, 4) ||
        (m->init >= m->text_end && m->init < m->patch_off))) ||
        m->init_arraysz % 8 || m->init_array % 8 ||
        !g2m_span(m->size, m->init_array, m->init_arraysz)) return "init_range";
    if (rela_ent != sizeof(Elf64_Rela) || (relasz[1] && plt_kind != DT_RELA)) return "relocation_format";
    uint64_t rx = (m->text_end + 0x3fff) & ~UINT64_C(0x3fff);
    for (unsigned t = 0; t < 2; t++) {
        if (rela[t] % 8 || relasz[t] % sizeof(Elf64_Rela) ||
            !g2m_span(m->size, rela[t], relasz[t]) || (relasz[t] && !rela[t])) return "relocation_table_range";
        for (uint64_t at = 0; at < relasz[t]; at += sizeof(Elf64_Rela)) {
            Elf64_Rela r; memcpy(&r, m->base + rela[t] + at, sizeof r);
            uint32_t type = (uint32_t)ELF64_R_TYPE(r.r_info);
            uint64_t si = ELF64_R_SYM(r.r_info);
            if (type != R_AARCH64_RELATIVE && type != R_AARCH64_ABS64 &&
                type != R_AARCH64_GLOB_DAT && type != R_AARCH64_JUMP_SLOT) return "relocation_unsupported";
            if (r.r_offset < rx || r.r_offset % 8 || !g2m_span(m->key_page_off, r.r_offset, 8))
                return "relocation_destination";
            if ((type == R_AARCH64_RELATIVE && si != 0) || (type != R_AARCH64_RELATIVE && si >= nsym))
                return "relocation_symbol_index";
            /* Protect the validation graph from being overwritten by a prior relocation. */
            uint64_t starts[] = {dynoff, sym, str, rela[0], rela[1]};
            uint64_t lengths[] = {ndyn * sizeof(Elf64_Dyn), str - sym, strsz, relasz[0], relasz[1]};
            for (unsigned j = 0; j < 5; j++)
                if (lengths[j] && r.r_offset < starts[j] + lengths[j] && starts[j] < r.r_offset + 8)
                    return "relocation_metadata_overlap";
        }
    }
    m->dyn = (const Elf64_Dyn *)(m->base + dynoff);
    m->symtab = (const Elf64_Sym *)(m->base + sym);
    m->strtab = (const char *)(m->base + str);
    m->nsym = (unsigned)nsym;
    return NULL;
}

static inline const char *g2m_gate_line(const module_t *m, const char *line,
                                       uint64_t *ret, char kind[16], int *arg, uint64_t *orig) {
    char words[4][32];
    const char *p = line;
    for (unsigned i = 0; i < 4; i++) {
        while (isspace((unsigned char)*p)) p++;
        const char *begin = p;
        while (*p && !isspace((unsigned char)*p)) p++;
        size_t length = (size_t)(p - begin);
        if (!length || length >= sizeof words[0]) return "gate_syntax";
        memcpy(words[i], begin, length); words[i][length] = 0;
    }
    while (isspace((unsigned char)*p)) p++;
    if (*p) return "gate_trailing_data";
    uint64_t values[3]; unsigned indexes[] = {0, 2, 3};
    for (unsigned i = 0; i < 3; i++) {
        char *end;
        const char *text = words[indexes[i]];
        if (!isdigit((unsigned char)*text)) return "gate_number";
        errno = 0;
        values[i] = strtoull(text, &end, i == 1 ? 10 : 16);
        if (errno == ERANGE || *end) return "gate_number";
    }
    if (values[0] < m->patch_off || values[0] % 4 || !g2m_span(m->size, values[0], 4) ||
        values[2] % 4 || !g2m_span(m->text_end, values[2], 4)) return "gate_offset";
    if (!strcmp(words[1], "svc")) { if (values[1] > 65535) return "gate_argument"; }
    else if (!strcmp(words[1], "obs")) { if (!values[1] || values[1] >= OBS_MAX) return "gate_argument"; }
    else if (!strcmp(words[1], "cntpct") || !strcmp(words[1], "cntvct")) {
        if (values[1] > 30) return "gate_register_index";
    } else return "gate_kind";
    *ret = values[0]; *orig = values[2]; *arg = (int)values[1];
    strcpy(kind, words[1]);
    return NULL;
}
