"""MAPS-ALF (branch B): offline luma ALF tools.

``spec``    reference classification and filtering of VVC luma ALF (numpy)
``wiener``  per-class (weighted) least-squares coefficient design with clipping-index search
``project`` projection of real-valued coefficients onto valid ALF syntax, export for the VTM hook
``weights`` per-pixel task weights (pseudo-label boxes, Hutchinson estimate of diag(J^T J))
``oracle``  O1-A: gradient-based upper bound through a differentiable ALF (torch)

Scope and known approximations (to be closed by the ALF audit against the pinned VTM):
- luma only; chroma ALF and CC-ALF are out of scope for the screening;
- no ALF virtual boundary handling (VVC pads samples across a virtual boundary 4 luma rows above each CTU's
  bottom edge and changes the classification there), so results differ from VTM on those rows;
- picture-boundary handling = coordinate clamping (replicate padding);
- constants marked VERIFY in ``spec`` must be checked against the VTM source before any bit-exact claim.
"""
