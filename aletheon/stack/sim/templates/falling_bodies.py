#!/usr/bin/env python3
"""Vetted sim template: N rigid bodies dropped on a ground plane (DESIGN.md §10).

[TEST] This template targets the Newton 1.x Python API (the warp.sim successor) and MUST be
validated against the installed release at the phase-9 gate — Newton is new and moving;
treat API drift here as expected, fix once, keep vetted. Params arrive pre-validated by
simrun against sim/registry.json (never trust argv beyond that contract).
Visualization: Newton's rerun viewer; simrun passes --grpc-port/--web-port so the dashboard
iframe URL is derived from the run, with viewer version == installed rerun SDK version.
"""
import argparse
import json


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--params", default=None)
    ap.add_argument("--grpc-port", type=int, default=9876)
    ap.add_argument("--web-port", type=int, default=9090)
    args = ap.parse_args()
    p = {"count": 50, "size": 0.25, "seconds": 15, "shape": "box"}
    if args.params:
        with open(args.params) as f:
            p.update(json.load(f))

    import rerun as rr  # noqa: F401 — serve the viewer the dashboard iframes
    rr.init("aletheon-sim", spawn=False)
    server_uri = rr.serve_grpc(grpc_port=args.grpc_port)
    rr.serve_web_viewer(web_port=args.web_port, connect_to=server_uri)

    import newton  # [TEST] API surface against installed release

    builder = newton.ModelBuilder()
    builder.add_ground_plane()
    rng_positions = [(i % 10 - 5.0, 2.0 + (i // 10) * (2.5 * p["size"]), (i * 7) % 10 - 5.0)
                     for i in range(int(p["count"]))]
    for i, (x, y, z) in enumerate(rng_positions):
        b = builder.add_body(xform=newton.math.transform((x, y, z)), key=f"body{i}")
        if p["shape"] == "sphere":
            builder.add_shape_sphere(b, radius=p["size"])
        else:
            builder.add_shape_box(b, hx=p["size"], hy=p["size"], hz=p["size"])
    model = builder.finalize()

    solver = newton.solvers.SolverXPBD(model)
    viewer = newton.viewer.ViewerRerun(server=False)  # log into the already-serving process
    viewer.set_model(model)

    fps, substeps = 60, 4
    state0, state1 = model.state(), model.state()
    control = model.control()
    dt = 1.0 / (fps * substeps)
    for frame in range(int(p["seconds"] * fps)):
        for _ in range(substeps):
            state0.clear_forces()
            solver.step(state0, state1, control, None, dt)
            state0, state1 = state1, state0
        viewer.begin_frame(frame / fps)
        viewer.log_state(state0)
        viewer.end_frame()
    print(json.dumps({"done": True, "frames": int(p["seconds"] * fps),
                      "viewer": f"http://127.0.0.1:{args.web_port}"}))


if __name__ == "__main__":
    main()
