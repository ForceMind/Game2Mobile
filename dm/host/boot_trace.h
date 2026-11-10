#ifndef DM_BOOT_TRACE_H
#define DM_BOOT_TRACE_H

/* Structured boot evidence, schema 1. This API is for ordinary threads only:
 * it uses pthread/stdio locks and MUST NOT be called from a signal handler.
 * The run receipt is read once, on the first event. No paths or free-form
 * diagnostics belong in these fields; existing logs retain those details.
 */

/* Returns 1 when the complete record was written and flushed, otherwise 0.
 * stage/status are fixed protocol tokens. code is empty or [a-z0-9_]{1,63}.
 * module is optional, [A-Za-z0-9_]{1,15}; invalid module names are omitted.
 * Invalid stage/status/code emits nothing and does not consume a sequence.
 */
int dm_boot_event(const char *stage, const char *status, const char *code,
                  const char *module);

/* At most one record of each kind per process, across all threads. After the
 * first attempt each hook only performs a relaxed atomic load and returns;
 * there is no per-frame getenv, timestamp, formatting, lock, or I/O.
 */
void dm_boot_gpu_submitted(void);
void dm_boot_presented(void);

/* Instantiate in one graphics translation unit for binaries without the host.
 * Undefined weak imports still fail a standalone Darwin executable link, so
 * provide actual weak definitions, as the other graphics-only hooks do. The
 * host's boot_trace.c definitions remain strong and replace these at link time.
 * noinline prevents a call being reduced to the empty fallback before linking.
 * Tests instantiate this same definition in a separate optimized object and
 * verify that linking boot_trace.c restores real events in either link order.
 */
#define DM_BOOT_TRACE_DEFINE_FALLBACKS() \
    __attribute__((weak, noinline)) void dm_boot_gpu_submitted(void) {} \
    __attribute__((weak, noinline)) void dm_boot_presented(void) {}

#endif
