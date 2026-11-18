# Real host reconstruction, replayable after assessment

The existing host gave a fresh candidate worker only actual objdump/GDB output and selected black-box observations. The integrator authored the reference, so the integrator is not presented as a blind reverse engineer. The worker reported its exact materials. No reference C or hidden fixture/expectation was supplied to it. Shared filesystem isolation was cooperative, not OS-enforced.

V1 candidate passed first attempt (six assessment groups plus one unexposed sealed boundary). We did not inject a bad implementation. A controlled owner-issued V2 pricing/weight change then caused four real failed groups. The same independent host worker inspected new machine-code/runtime evidence and approved public differences, changed three constants and passed six development/assessment groups and seven groups including the still-unexposed sealed boundary.

Both independently written revisions are preserved here. Now-public replay inputs are no longer a hidden assessment; tools/replay_reconstruction.py reproduces engineering differences and regressions, not a new blind-model performance score. The counter demo is separate. See docs/goal evidence for exact hashes, execution and limitations.
