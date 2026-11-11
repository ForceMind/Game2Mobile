/* Fault injection at the real mprotect boundary; no game or GPU execution. */
#define mprotect injected_mprotect
#include "../nvn/nvn_dirty.c"
#undef mprotect
#include <assert.h>
#include <errno.h>
int mprotect(void *, size_t, int);
static int reject_read, reject_write;
int injected_mprotect(void *addr, size_t length, int protection) {
    if ((reject_read && protection == PROT_READ) || (reject_write && (protection & PROT_WRITE))) {
        errno = EACCES; return -1;
    }
    return mprotect(addr, length, protection);
}
void dm_fault_hook_register(int (*f)(void *, int, void *)) { (void)f; }
void dm_guest_write_prep_register(void (*f)(void *, size_t)) { (void)f; }
int main(void) {
    size_t pg = (size_t)getpagesize();
    void *p = mmap(NULL, pg, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANON, -1, 0);
    assert(p != MAP_FAILED);
    nvn_dirty_add_range(p, pg);
    uint64_t stamp = nvn_dirty_now();
    reject_read = 1; nvn_dirty_protect(p, pg); reject_read = 0;
    assert(!nvn_dirty_tracked(p, pg));
    assert(nvn_dirty_since(p, pg, stamp));
    assert(nvn_dirty_since(p, pg, nvn_dirty_now())); /* Failed tracking stays conservative. */
    prep_write(p, pg); ((char *)p)[0] = 1;
    nvn_dirty_remove_range(p);
    nvn_dirty_add_range(p, pg); /* A new pool may track again. */
    assert(nvn_dirty_tracked(p, pg));
    nvn_dirty_protect(p, pg);
    reject_write = 1;
    assert(on_fault(p, 1, NULL) == 0); /* Must propagate, not endless retry. */
    assert(atomic_load(&find((uintptr_t)p)->state[0]) != PG_BUSY);
    assert(nvn_dirty_since(p, pg, nvn_dirty_now()));
    reject_write = 0; prep_write(p, pg); ((char *)p)[0] = 2;
    nvn_dirty_remove_range(p); munmap(p, pg);
    int before, used; uint64_t adds;
    nvn_dirty_slot_stats(&before, &used, &adds);
    nvn_dirty_add_range((void *)(UINTPTR_MAX - 7), 64);
    nvn_dirty_add_range(NULL, pg); nvn_dirty_add_range(p, 0);
    int after; uint64_t after_adds; nvn_dirty_slot_stats(&after, &used, &after_adds);
    assert(before == after && adds == after_adds);
    assert(!nvn_dirty_tracked((void *)(UINTPTR_MAX - 4), SIZE_MAX));
    assert(nvn_dirty_since(p, SIZE_MAX, 0));
    puts("dirty tracker: protection failures, recovery and range overflow passed");
    return 0;
}
