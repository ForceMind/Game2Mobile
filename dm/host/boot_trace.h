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

/* Graphics-only tests do not link the host. They may include this header with
 * DM_BOOT_TRACE_OPTIONAL and guard the two hook calls with a null check. The
 * real host links strong definitions from boot_trace.c via its source list.
 */
#if defined(DM_BOOT_TRACE_OPTIONAL) && defined(__APPLE__)
#define DM_BOOT_TRACE_LINK __attribute__((weak_import))
#elif defined(DM_BOOT_TRACE_OPTIONAL) && defined(__GNUC__)
#define DM_BOOT_TRACE_LINK __attribute__((weak))
#else
#define DM_BOOT_TRACE_LINK
#endif

/* At most one record of each kind per process, across all threads. After the
 * first attempt each hook only performs a relaxed atomic load and returns;
 * there is no per-frame getenv, timestamp, formatting, lock, or I/O.
 */
void dm_boot_gpu_submitted(void) DM_BOOT_TRACE_LINK;
void dm_boot_presented(void) DM_BOOT_TRACE_LINK;

#undef DM_BOOT_TRACE_LINK
#endif
