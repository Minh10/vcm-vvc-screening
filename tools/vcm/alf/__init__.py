"""MAPS-ALF (branch B): offline luma ALF tools.

``spec``    reference classification and filtering of VVC luma ALF (numpy)
``wiener``  per-class (weighted) least-squares coefficient design with clipping-index search
``project`` projection of real-valued coefficients onto valid ALF syntax, export for the VTM hook
``weights`` per-pixel task weights (pseudo-label boxes, Hutchinson estimate of diag(J^T J))
``oracle``  O1-A: gradient-based relaxed oracle through a differentiable ALF (torch)
``dump``    reader of the VTM ALF dump hook (pre/post-ALF luma, per-CTB filters)

Scope (docs/ALF_CODEC_AUDIT.md):
- luma only; chroma ALF and CC-ALF are out of scope for the screening;
- ``spec`` is bit-exact with VTM-24.0 luma ALF (classification, virtual boundary at CTU-4 rows, clipping,
  rounding), verified against a literal port of the VTM C++ and against VTM's own dump (tests/test_alf.py);
- picture boundaries: replicate padding as in VTM; single-slice, single-tile pictures only (as in the CTC).
"""
