#include "../nvn/nvn_dirty.h"
#include "../../host/dm.h"
#include <sys/mman.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

module_t g_mod[MAX_MOD];
int g_nmod;
module_t *module_of(const void *p) { (void)p; return NULL; }
void crash_install(void);

static int g_fail;
#define EXPECT(name, want, got) do { \
    long long want_ = (long long)(want), got_ = (long long)(got); \
    printf("%-52s 期望 %-4lld → 真结果 %-4lld %s\n", name, want_, got_, want_ == got_ ? "✓" : "✗"); \
    if (want_ != got_) g_fail++; \
} while (0)

static void *page_map(void) {
    void *p = mmap(NULL, 4096, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANON, -1, 0);
    if (p == MAP_FAILED) { perror("mmap"); exit(2); }
    return p;
}

int main(void) {
    crash_install();

    for (int i = 0; i < 65; i++) {
        void *p = page_map();
        nvn_dirty_add_range(p, 4096);
        nvn_dirty_remove_range(p);
        munmap(p, 4096);
    }

    void *reused = page_map();
    nvn_dirty_add_range(reused, 4096);
    nvn_dirty_protect(reused, 4096);
    uint64_t stamp = nvn_dirty_now();
    ((volatile uint8_t *)reused)[0] = 1;
    EXPECT("累计 65 次销池后新池写入被判脏", 1, nvn_dirty_since(reused, 4096, stamp));
    nvn_dirty_remove_range(reused);
    munmap(reused, 4096);

    // A reused pool at precisely the same address is a new resource identity.
    // A cache entry from the previous incarnation must be invalidated before
    // any guest write, while a stamp acquired after re-registration is current.
    void *same = page_map();
    nvn_dirty_add_range(same, 4096);
    uint64_t old_stamp = nvn_dirty_now();
    nvn_dirty_remove_range(same);
    nvn_dirty_add_range(same, 4096);
    EXPECT("同地址新建内存池必须使旧纹理戳失效", 1, nvn_dirty_since(same, 4096, old_stamp));
    stamp = nvn_dirty_now();
    EXPECT("重建后新戳且未写入不应反复判脏", 0, nvn_dirty_since(same, 4096, stamp));
    nvn_dirty_remove_range(same);
    munmap(same, 4096);

    // Use the actual runtime capacity. The old hardcoded 300 test did not
    // overflow after MAX_RANGE grew from 256 to 4096, so it gave false comfort.
    int live_count = 0, peak = 0, cap = 0;
    nvn_dirty_stat(&live_count, &peak, &cap);
    if (cap < 1) { fprintf(stderr, "invalid dirty range capacity\n"); return 2; }
    void **live = calloc((size_t)cap + 1, sizeof(*live));
    if (!live) { perror("calloc"); return 2; }
    for (int i = 0; i <= cap; i++) {
        live[i] = page_map();
        nvn_dirty_add_range(live[i], 4096);
    }
    void *overflow = live[cap];
    EXPECT("超过实际容量的池必须未跟踪", 0, nvn_dirty_tracked(overflow, 4096));
    stamp = nvn_dirty_now();
    nvn_dirty_protect(overflow, 4096);
    ((volatile uint8_t *)overflow)[0] = 2;
    EXPECT("容量溢出的池保守判脏", 1, nvn_dirty_since(overflow, 4096, stamp));
    for (int i = 0; i <= cap; i++) {
        nvn_dirty_remove_range(live[i]);
        munmap(live[i], 4096);
    }
    free(live);
    return g_fail != 0;
}
