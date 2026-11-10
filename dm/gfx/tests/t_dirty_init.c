// First-registration race: no guest thread may add a pool before both hooks
// have finished installing. This is an asset-free real ARM64 concurrency test.
#include <stdatomic.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <unistd.h>

static _Atomic int ready, go, entered, release_hook, hooks_ready;
static _Atomic int finished, before_hooks, errors, fault_calls, prep_calls;
static void *g_pools[32];

void test_fault_register(int (*fn)(void *, int, void *)) {
    (void)fn;
    atomic_fetch_add(&fault_calls, 1);
    atomic_store(&entered, 1);
    while (!atomic_load(&release_hook)) usleep(200);
}
void test_prep_register(void (*fn)(void *, size_t)) {
    (void)fn;
    atomic_fetch_add(&prep_calls, 1);
    atomic_store(&hooks_ready, 1);
}
#define dm_fault_hook_register test_fault_register
#define dm_guest_write_prep_register test_prep_register
#include "../nvn/nvn_dirty.c"
#undef dm_fault_hook_register
#undef dm_guest_write_prep_register

module_t g_mod[MAX_MOD];
int g_nmod;
module_t *module_of(const void *p) { (void)p; return NULL; }
void crash_install(void);

static void *worker(void *arg) {
    size_t idx = (size_t)(uintptr_t)arg;
    atomic_fetch_add(&ready, 1);
    while (!atomic_load(&go)) usleep(100);
    size_t n = (size_t)getpagesize();
    void *p = mmap(NULL, n, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANON, -1, 0);
    if (p == MAP_FAILED) { atomic_fetch_add(&errors, 1); return NULL; }
    g_pools[idx] = p;
    nvn_dirty_add_range(p, n);
    if (!atomic_load(&hooks_ready)) atomic_fetch_add(&before_hooks, 1);
    if (!nvn_dirty_tracked(p, n)) atomic_fetch_add(&errors, 1);
    // Keep all ranges alive until every registration has completed: this
    // test isolates hook initialization, not concurrent pool destruction.
    atomic_fetch_add(&finished, 1);
    return NULL;
}

int main(void) {
    enum { THREADS = 32 };
    pthread_t threads[THREADS];
    for (int i = 0; i < THREADS; i++) {
        if (pthread_create(&threads[i], NULL, worker, (void *)(uintptr_t)i)) {
            fprintf(stderr, "pthread_create failure\n"); return 2;
        }
    }
    for (int n = 0; n < 2000 && atomic_load(&ready) != THREADS; n++) usleep(1000);
    if (atomic_load(&ready) != THREADS) { atomic_store(&release_hook, 1); return 2; }
    atomic_store(&go, 1);
    for (int n = 0; n < 2000 && !atomic_load(&entered); n++) usleep(1000);
    if (!atomic_load(&entered)) { atomic_store(&release_hook, 1); return 2; }
    usleep(50000); // Other threads attempt registration while first hook is held.
    int premature = atomic_load(&before_hooks);
    atomic_store(&release_hook, 1);
    for (int i = 0; i < THREADS; i++) pthread_join(threads[i], NULL);
    for (int i = 0; i < THREADS; i++) {
        if (g_pools[i]) {
            nvn_dirty_remove_range(g_pools[i]);
            munmap(g_pools[i], (size_t)getpagesize());
        }
    }
    int wrong = premature + atomic_load(&errors) +
                (atomic_load(&finished) != THREADS) +
                (atomic_load(&fault_calls) != 1) +
                (atomic_load(&prep_calls) != 1);
    printf("dirty init: hooks=%d/%d premature=%d finished=%d errors=%d %s\n",
           atomic_load(&fault_calls), atomic_load(&prep_calls),
           premature, atomic_load(&finished), atomic_load(&errors),
           wrong ? "FAIL" : "PASS");
    return wrong != 0;
}
