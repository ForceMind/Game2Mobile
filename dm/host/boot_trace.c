#ifndef _POSIX_C_SOURCE
#define _POSIX_C_SOURCE 200809L
#endif
#include "boot_trace.h"
#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

static pthread_once_t g_init = PTHREAD_ONCE_INIT;
static pthread_mutex_t g_lock = PTHREAD_MUTEX_INITIALIZER;
static char g_run_id[33];
static uint64_t g_start_ns, g_elapsed_ns, g_seq;
static _Atomic unsigned g_gpu_submitted, g_presented;

static uint64_t clock_ns(clockid_t clock) {
    struct timespec ts;
    if (clock_gettime(clock, &ts)) return 0;
    return (uint64_t)ts.tv_sec * UINT64_C(1000000000) + (uint64_t)ts.tv_nsec;
}

static int valid_receipt(const char *receipt) {
    if (!receipt) return 0;
    for (unsigned i = 0; i < 32; i++) {
        unsigned char c = (unsigned char)receipt[i];
        if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) return 0;
    }
    return receipt[32] == '\0';
}

/* An opaque process correlation ID, not a cryptographic identity or secret. */
static uint64_t mix_id(uint64_t value) {
    value = (value ^ (value >> 30)) * UINT64_C(0xbf58476d1ce4e5b9);
    value = (value ^ (value >> 27)) * UINT64_C(0x94d049bb133111eb);
    return value ^ (value >> 31);
}

static void trace_init(void) {
    g_start_ns = clock_ns(CLOCK_MONOTONIC);
    const char *receipt = getenv("DM_RUN_RECEIPT");
    if (valid_receipt(receipt)) {
        memcpy(g_run_id, receipt, sizeof g_run_id);
        return;
    }
    uint64_t pid = (uint64_t)getpid();
    uint64_t first = mix_id(clock_ns(CLOCK_REALTIME) ^ g_start_ns ^ (pid << 32));
    uint64_t second = mix_id(first + UINT64_C(0x9e3779b97f4a7c15) + pid);
    (void)snprintf(g_run_id, sizeof g_run_id, "%016llx%016llx",
                   (unsigned long long)first, (unsigned long long)second);
}

static int valid_stage(const char *stage) {
    static const char *const stages[] = {
        "host_start", "module_load", "relocation", "sdk_init", "module_init",
        "guest_entry", "gpu_submit", "first_present", "host_return"
    };
    if (!stage) return 0;
    for (unsigned i = 0; i < sizeof stages / sizeof stages[0]; i++)
        if (!strcmp(stage, stages[i])) return 1;
    return 0;
}

static int valid_token(const char *token, unsigned max_length, int upper) {
    if (!token || !*token) return 0;
    for (unsigned i = 0; i <= max_length; i++) {
        unsigned char c = (unsigned char)token[i];
        if (!c) return 1;
        if (i == max_length || !((c >= 'a' && c <= 'z') ||
            (c >= '0' && c <= '9') || c == '_' ||
            (upper && c >= 'A' && c <= 'Z'))) return 0;
    }
    return 0;
}

/* Caller holds g_lock. The file lock keeps each JSON record intact even when
 * unrelated threads write ordinary diagnostics to stderr. A leading newline
 * isolates the record if an existing fprintf/fputc log is between its writes.
 * Integer formatting keeps elapsed_ms valid JSON with a comma locale too.
 */
static int emit_locked(const char *stage, const char *status, const char *code,
                       const char *module) {
    uint64_t now = clock_ns(CLOCK_MONOTONIC);
    if (!g_start_ns) g_start_ns = now;
    uint64_t elapsed = now >= g_start_ns ? now - g_start_ns : g_elapsed_ns;
    if (elapsed < g_elapsed_ns) elapsed = g_elapsed_ns;
    g_elapsed_ns = elapsed;
    char line[512];
    int n = snprintf(line, sizeof line,
        "\nG2M_BOOT {\"schema\":1,\"run_id\":\"%s\",\"seq\":%llu,"
        "\"elapsed_ms\":%llu.%03llu,\"stage\":\"%s\",\"status\":\"%s\",\"code\":\"%s\"%s%s%s}\n",
        g_run_id, (unsigned long long)++g_seq,
        (unsigned long long)(elapsed / UINT64_C(1000000)),
        (unsigned long long)((elapsed / UINT64_C(1000)) % 1000), stage, status, code,
        module ? ",\"module\":\"" : "", module ? module : "", module ? "\"" : "");
    if (n < 0 || (size_t)n >= sizeof line) return 0;
    flockfile(stderr);
    int ok = fwrite(line, 1, (size_t)n, stderr) == (size_t)n;
    if (fflush(stderr)) ok = 0;
    funlockfile(stderr);
    return ok;
}

int dm_boot_event(const char *stage, const char *status, const char *code,
                  const char *module) {
    int saved_errno = errno;
    if (!valid_stage(stage) || !status ||
        (strcmp(status, "begin") && strcmp(status, "ok") && strcmp(status, "error")) ||
        (code && *code && !valid_token(code, 63, 0))) return 0;
    if (!valid_token(module, 15, 1)) module = NULL;
    pthread_once(&g_init, trace_init);
    pthread_mutex_lock(&g_lock);
    int ok = emit_locked(stage, status, code ? code : "", module);
    pthread_mutex_unlock(&g_lock);
    errno = saved_errno;
    return ok;
}

static void emit_once(_Atomic unsigned *done, const char *stage) {
    if (atomic_load_explicit(done, memory_order_relaxed)) return;
    int saved_errno = errno;
    pthread_once(&g_init, trace_init);
    pthread_mutex_lock(&g_lock);
    if (!atomic_load_explicit(done, memory_order_relaxed)) {
        (void)emit_locked(stage, "ok", "", NULL);
        /* Count the attempt even on a broken stderr; do not retry every frame. */
        atomic_store_explicit(done, 1, memory_order_relaxed);
    }
    pthread_mutex_unlock(&g_lock);
    errno = saved_errno;
}

void dm_boot_gpu_submitted(void) { emit_once(&g_gpu_submitted, "gpu_submit"); }
void dm_boot_presented(void) { emit_once(&g_presented, "first_present"); }
