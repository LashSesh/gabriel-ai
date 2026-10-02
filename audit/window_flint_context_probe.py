"""Bounded reproducer for the global python-flint precision-context observation.

Run in a fresh process with the recorded python-flint installation available.
This is a context-visibility probe, not a certificate or throughput benchmark.
The original development invocation's output is retained separately as
window_flint_context_probe_observed.txt; this saved file was not rerun during
the manuscript/timing freeze.
"""
import threading

from flint import ctx


ready = threading.Event()
done = threading.Event()


def writer():
    with ctx.workprec(32):
        ready.set()
        done.wait(2)


original = ctx.prec
with ctx.workprec(512):
    thread = threading.Thread(target=writer)
    thread.start()
    if not ready.wait(2):
        done.set()
        thread.join(2)
        raise RuntimeError('worker did not enter the precision context')
    print({'main_expected_workprec': 512,
           'main_observed_other_thread_precision': ctx.prec})
    done.set()
    thread.join(2)
    if thread.is_alive():
        raise RuntimeError('worker did not exit')
print({'restored_precision': ctx.prec, 'original': original})
