#define _POSIX_C_SOURCE 200809L
#include "../boot_trace.h"

#ifdef DM_BOOT_TRACE_OPTIONAL
DM_BOOT_TRACE_DEFINE_FALLBACKS()
int main(void) {
    dm_boot_gpu_submitted();
    dm_boot_presented();
    return 0;
}
#else
#include <errno.h>
#include <pthread.h>
#include <sched.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { WORKERS = 8, EVENTS = 128 };
static _Atomic unsigned g_ready, g_start;

static void *worker(void *argument) {
    unsigned id = (unsigned)(uintptr_t)argument;
    atomic_fetch_add_explicit(&g_ready, 1, memory_order_relaxed);
    while (!atomic_load_explicit(&g_start, memory_order_relaxed)) sched_yield();
    for (unsigned i = 0; i < EVENTS; i++) {
        errno = EDOM;
        if (!dm_boot_event("module_load", "ok", "", "sdk") || errno != EDOM)
            return (void *)(uintptr_t)1;
        dm_boot_gpu_submitted();
        dm_boot_presented();
        if (errno != EDOM) return (void *)(uintptr_t)1;
        if (i % 16 == 0) {
            /* Match the runtime's split fprintf/fputc diagnostic macro, with
             * extra scheduling pressure between its two writes. */
            fprintf(stderr, "fixture diagnostic from worker %u", id);
            sched_yield();
            fputc('\n', stderr);
        }
    }
    return NULL;
}

static int threaded(void) {
    pthread_t threads[WORKERS];
    for (unsigned i = 0; i < WORKERS; i++)
        if (pthread_create(&threads[i], NULL, worker, (void *)(uintptr_t)i)) return 1;
    while (atomic_load_explicit(&g_ready, memory_order_relaxed) != WORKERS) sched_yield();
    atomic_store_explicit(&g_start, 1, memory_order_relaxed);
    for (unsigned i = 0; i < WORKERS; i++) {
        void *result;
        if (pthread_join(threads[i], &result) || result) return 1;
    }
    return 0;
}

static int invalid_fields(void) {
    if (dm_boot_event("unknown", "ok", "", NULL) ||
        dm_boot_event(NULL, "ok", "", NULL) ||
        dm_boot_event("host_start", "other", "", NULL) ||
        dm_boot_event("host_start", NULL, "", NULL) ||
        dm_boot_event("host_start", "ok", "secret\nvalue", NULL) ||
        dm_boot_event("host_start", "ok", "UPPER_CASE", NULL) ||
        dm_boot_event("host_start", "ok",
            "this_code_is_deliberately_longer_than_the_sixty_three_character_limit", NULL)) return 1;
    if (!dm_boot_event("module_load", "begin", "", "sdk")) return 1;
    if (!dm_boot_event("module_load", "ok", NULL, "../../secret/path")) return 1;
    if (!dm_boot_event("relocation", "error", "missing_symbol", "secret\"\nfield")) return 1;
    if (!dm_boot_event("module_init", "ok", "", "module_name_longer_than_15")) return 1;
    return 0;
}

int main(int argc, char **argv) {
    if (argc > 1 && !strcmp(argv[1], "threads")) return threaded();
    if (argc > 1 && !strcmp(argv[1], "invalid")) return invalid_fields();
    int present_before_submit = argc > 1 && !strcmp(argv[1], "present_before_submit");
    int gpu_during_init = argc > 1 && !strcmp(argv[1], "gpu_during_init");
    errno = EDOM;
    if (!dm_boot_event("host_start", "begin", "", NULL) || errno != EDOM) return 1;
    if (argc > 1 && !strcmp(argv[1], "change_receipt"))
        if (setenv("DM_RUN_RECEIPT", "ffffffffffffffffffffffffffffffff", 1)) return 1;
    dm_boot_event("module_load", "begin", "layout", "main");
    dm_boot_event("module_load", "ok", "layout", "main");
    dm_boot_event("module_load", "begin", "image", "main");
    dm_boot_event("module_load", "ok", "image", "main");
    dm_boot_event("relocation", "begin", "", NULL);
    dm_boot_event("relocation", "ok", "", NULL);
    dm_boot_event("host_start", "ok", "", NULL);
    dm_boot_event("sdk_init", "begin", "", NULL);
    /* Guest constructors may call graphics before nnMain. This is a synthetic
     * observation order, not a claim about proprietary SDK execution. */
    if (gpu_during_init) {
        dm_boot_gpu_submitted();
        dm_boot_presented();
    }
    dm_boot_event("sdk_init", "ok", "", NULL);
    dm_boot_event("module_init", "begin", "", "main");
    dm_boot_event("module_init", "ok", "", "main");
    dm_boot_event("guest_entry", "begin", "", NULL);
    /* A real present callback may publish its observation while the first
     * submit thread is descheduled after Metal commit but before its log. */
    if (present_before_submit) dm_boot_presented();
    for (unsigned i = 0; i < 100; i++) {
        dm_boot_gpu_submitted();
        dm_boot_presented();
    }
    dm_boot_event("guest_entry", "ok", "returned", NULL);
    dm_boot_event("host_return", "ok", "returned", NULL);
    return 0;
}
#endif
