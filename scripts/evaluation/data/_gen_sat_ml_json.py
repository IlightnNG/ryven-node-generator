"""One-off generator for node_tasks_bench_sat_ml_v1.json — run: python _gen_sat_ml_json.py"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np


def K_flat(b_list, r_list, a_list):
    B = np.zeros((3, 3))
    z = np.zeros(3)
    for b, r, a in zip(b_list, r_list, a_list, strict=True):
        b = np.array(b, float)
        r = np.array(r, float)
        B += float(a) * np.outer(b, r)
        z += float(a) * np.cross(b, r)
    S = B + B.T
    sig = float(np.trace(B))
    K = np.zeros((4, 4))
    K[0, 0] = sig
    K[0, 1:4] = z
    K[1:4, 0] = z
    K[1:4, 1:4] = S - sig * np.eye(3)
    return K.flatten().tolist()


def main() -> None:
    out_path = Path(__file__).resolve().parent / "node_tasks_bench_sat_ml_v1.json"

    k_n1 = K_flat([[1, 0, 0]], [[1, 0, 0]], [1.0])
    k_n1_orth = K_flat([[1, 0, 0]], [[0, 1, 0]], [1.0])

    Kmat = np.array(k_n1).reshape(4, 4)
    _w, v = np.linalg.eigh(Kmat)
    q_n18 = [float(x) for x in v[:, -1]]

    doc = (
        "20 satellite / attitude / TF / PyTorch benchmark tasks aligned with node_tasks_bench_sat_ml_en.md. "
        "Ports are fixed for automated stub_runner checks. core_logic uses self.get_input_val(i) and "
        "self.set_output_val(j, Data(...)). N13–N14 require tensorflow; N15–N16, N20 require torch. "
        "Some L3 rows use strict:false for float/sign tolerance."
    )

    tasks: list[dict] = []

    def T(
        tid: str,
        band: str,
        title: str,
        cls: str,
        zh: str,
        inputs: list,
        outputs: list,
        req: str,
        tags: list,
        demo: list,
        robust: list,
        **extra,
    ):
        tasks.append(
            {
                "task_id": tid,
                "band": band,
                "title": title,
                "class_name_suggestion": cls,
                "description_zh": zh,
                "description_en": extra.get("description_en", ""),
                "inputs": inputs,
                "outputs": outputs,
                "core_logic_requirement": req,
                "tags": tags,
                "demo_stub_cases": demo,
                "robust_stub_cases": robust,
                **{k: v for k, v in extra.items() if k != "description_en"},
            }
        )

    # --- L1 ---
    T(
        "N01",
        "L1",
        "Body-frame direction normalize",
        "SatNormalizeDirNode",
        "将三维方向向量单位化（L2=1）；零向量按约定输出。",
        [{"label": "raw_v", "type": "data"}],
        [{"label": "unit_v", "type": "data"}],
        "Input: length-3 iterable raw_v. Output unit_v = raw_v / ||raw_v|| if norm > eps else Data([0.0,0.0,0.0]) (document eps). Use numpy.",
        ["satellite", "vector"],
        [
            {"inputs": [[3.0, 0.0, 0.0]], "expected_outputs": {"0": [1.0, 0.0, 0.0]}, "strict": True},
            {"inputs": [[0.0, 4.0, 0.0]], "expected_outputs": {"0": [0.0, 1.0, 0.0]}, "strict": True},
        ],
        [
            {"inputs": [[0.0, 0.0, 0.0]], "expected_outputs": {"0": [0.0, 0.0, 0.0]}, "strict": True},
            {"inputs": [None], "expected_outputs": {"0": [0.0, 0.0, 0.0]}, "strict": False},
        ],
    )

    T(
        "N02",
        "L1",
        "Magnetometer magnitude and unit vector",
        "SatMagUnitNode",
        "三轴磁强计模长与单位方向。",
        [{"label": "b", "type": "data"}],
        [{"label": "mag", "type": "data"}, {"label": "b_hat", "type": "data"}],
        "b is length-3. Output mag = float norm; b_hat = b/mag if mag>eps else Data([0,0,0]). Match numpy.linalg.norm.",
        ["satellite", "vector"],
        [
            {"inputs": [[0.0, 0.0, 5.0]], "expected_outputs": {"0": 5.0, "1": [0.0, 0.0, 1.0]}, "strict": True},
        ],
        [
            {"inputs": [[0.0, 0.0, 0.0]], "expected_outputs": {"0": 0.0, "1": [0.0, 0.0, 0.0]}, "strict": False},
        ],
    )

    T(
        "N03",
        "L1",
        "Angle between 3D vectors (rad)",
        "SatVecAngleNode",
        "两向量夹角 [0, pi]（弧度）。",
        [{"label": "u", "type": "data"}, {"label": "v", "type": "data"}],
        [{"label": "angle", "type": "data"}],
        "u,v length-3. angle = arccos(clip(dot(u_hat,v_hat),-1,1)) with safe handling of zero vectors (return 0.0 or documented sentinel).",
        ["satellite", "geometry"],
        [
            {"inputs": [[1, 0, 0], [1, 0, 0]], "expected_outputs": {"0": 0.0}, "strict": False},
            {"inputs": [[1, 0, 0], [0, 1, 0]], "expected_outputs": {"0": math.pi / 2}, "strict": False},
        ],
        [
            {"inputs": [[0, 0, 0], [1, 0, 0]], "expected_outputs": {"0": 0.0}, "strict": False},
        ],
    )

    T(
        "N04",
        "L1",
        "Cross and scalar triple product",
        "SatCrossTripleNode",
        "叉积与混合积。",
        [{"label": "a", "type": "data"}, {"label": "b", "type": "data"}, {"label": "c", "type": "data"}],
        [{"label": "axb", "type": "data"}, {"label": "triple", "type": "data"}],
        "a,b,c length-3. axb = numpy.cross(a,b); triple = numpy.dot(c, axb).",
        ["satellite", "vector"],
        [
            {
                "inputs": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                "expected_outputs": {"0": [0.0, 0.0, 1.0], "1": 1.0},
                "strict": True,
            },
        ],
        [
            {
                "inputs": [[1, 0, 0], [0, 1, 0], [1, 0, 0]],
                "expected_outputs": {"0": [0.0, 0.0, 1.0], "1": 0.0},
                "strict": True,
            },
        ],
    )

    T(
        "N05",
        "L1",
        "Quaternion conjugate (Hamilton w,x,y,z)",
        "SatQuatConjNode",
        "四元数共轭 q*。",
        [{"label": "q", "type": "data"}],
        [{"label": "q_conj", "type": "data"}],
        "q = [w,x,y,z] Hamilton. Conjugate [w,-x,-y,-z].",
        ["satellite", "quaternion"],
        [
            {"inputs": [[1.0, 2.0, 3.0, 4.0]], "expected_outputs": {"0": [1.0, -2.0, -3.0, -4.0]}, "strict": True},
        ],
        [
            {"inputs": [[0.0, 0.0, 0.0, 0.0]], "expected_outputs": {"0": [0.0, 0.0, 0.0, 0.0]}, "strict": False},
        ],
    )

    T(
        "N06",
        "L1",
        "Quaternion normalization",
        "SatQuatNormNode",
        "四元数归一化。",
        [{"label": "q", "type": "data"}],
        [{"label": "q_unit", "type": "data"}],
        "q length-4, q_unit = q / ||q||_2 if norm>eps else documented sentinel (e.g. [1,0,0,0] or zeros).",
        ["satellite", "quaternion"],
        [
            {"inputs": [[2.0, 0.0, 0.0, 0.0]], "expected_outputs": {"0": [1.0, 0.0, 0.0, 0.0]}, "strict": True},
        ],
        [
            {"inputs": [[0.0, 0.0, 0.0, 0.0]], "expected_outputs": {"0": [1.0, 0.0, 0.0, 0.0]}, "strict": False},
        ],
    )

    T(
        "N07",
        "L1",
        "Quaternion single-step integration",
        "SatQuatIntegrateNode",
        "角速度单步四元数积分。",
        [{"label": "q_k", "type": "data"}, {"label": "omega", "type": "data"}, {"label": "dt", "type": "data"}],
        [{"label": "q_next", "type": "data"}],
        "If float(dt)==0, output q_next equals q_k (element-wise). Otherwise implement one documented discrete step (first-order).",
        ["satellite", "quaternion"],
        [
            {
                "inputs": [[1, 0, 0, 0], [0.1, 0.2, 0.3], 0.0],
                "expected_outputs": {"0": [1.0, 0.0, 0.0, 0.0]},
                "strict": True,
            },
        ],
        [
            {
                "inputs": [[0.6, 0.8, 0.0, 0.0], [0.0, 0.0, 0.0], 0.0],
                "expected_outputs": {"0": [0.6, 0.8, 0.0, 0.0]},
                "strict": True,
            },
        ],
    )

    T(
        "N08",
        "L1",
        "Gyro bias correction",
        "SatGyroBiasNode",
        "陀螺角速度减偏置。",
        [{"label": "omega_raw", "type": "data"}, {"label": "bias", "type": "data"}],
        [{"label": "omega_corr", "type": "data"}],
        "Element-wise omega_raw - bias; length-3; None components -> 0.0.",
        ["satellite", "gyro"],
        [
            {
                "inputs": [[1.0, 2.0, 3.0], [0.0, 1.0, 2.0]],
                "expected_outputs": {"0": [1.0, 1.0, 1.0]},
                "strict": True,
            },
        ],
        [
            {
                "inputs": [[1.0, 2.0, 3.0], None],
                "expected_outputs": {"0": [1.0, 2.0, 3.0]},
                "strict": False,
            },
        ],
    )

    # --- L2 ---
    T(
        "N09",
        "L2",
        "DCM times body vector",
        "SatDcmApplyNode",
        "方向余弦矩阵乘体轴向量（行主序 9 标量 + 3 向量）。",
        [{"label": "R_flat", "type": "data"}, {"label": "v_b", "type": "data"}],
        [{"label": "v_r", "type": "data"}],
        "R_flat: 9 floats row-major 3x3 mapping v_r = R @ v_b (body to reference). Use numpy.reshape(3,3).",
        ["satellite", "attitude"],
        [
            {
                "inputs": [[1, 0, 0, 0, 1, 0, 0, 0, 1], [1, 2, 3]],
                "expected_outputs": {"0": [1.0, 2.0, 3.0]},
                "strict": True,
            },
            {
                "inputs": [[0, -1, 0, 1, 0, 0, 0, 0, 1], [1, 0, 0]],
                "expected_outputs": {"0": [0.0, 1.0, 0.0]},
                "strict": True,
            },
        ],
        [
            {
                "inputs": [[1, 0, 0, 0, 1, 0, 0, 0, 1], [0, 0, 0]],
                "expected_outputs": {"0": [0.0, 0.0, 0.0]},
                "strict": True,
            },
        ],
    )

    t10_flat = [1, 0, 0, 0, 0, 1, 0, -1, 0]  # columns t1,t2,t3 flattened row-major of 3x3
    T(
        "N10",
        "L2",
        "TRIAD precursor orthonormal frame",
        "SatTriadPrecursorNode",
        "由两体轴观测构造正交标架（3×3）。",
        [{"label": "b1", "type": "data"}, {"label": "b2", "type": "data"}],
        [{"label": "T_flat", "type": "data"}],
        "Unit b1,b2 (non-collinear). t1=b1/||b1||, t2=cross(b1,b2) normalized, t3=cross(t1,t2). Output T_flat: 9 floats row-major 3x3 with columns t1,t2,t3.",
        ["satellite", "triad"],
        [
            {
                "inputs": [[1, 0, 0], [0, 1, 0]],
                "expected_outputs": {"0": t10_flat},
                "strict": False,
            },
        ],
        [
            {
                "inputs": [[1, 0, 0], [0, 0, 1]],
                "expected_outputs": {"0": [1, 0, 0, 0, 1, 0, 0, 0, 1]},
                "strict": False,
            },
        ],
    )

    T(
        "N11",
        "L2",
        "Weighted direction fusion (N=4)",
        "SatWahbaWeightsNode",
        "四组加权单位向量融合为单位方向。",
        [
            {"label": "v1", "type": "data"},
            {"label": "v2", "type": "data"},
            {"label": "v3", "type": "data"},
            {"label": "v4", "type": "data"},
            {"label": "w1", "type": "data"},
            {"label": "w2", "type": "data"},
            {"label": "w3", "type": "data"},
            {"label": "w4", "type": "data"},
        ],
        [{"label": "u_out", "type": "data"}],
        "Weighted sum s = w1*v1+...+w4*v4; if ||s||<eps return [1,0,0] or documented sentinel; else output s/||s||.",
        ["satellite", "fusion"],
        [
            {
                "inputs": [[1, 0, 0], [0, 1, 0], [0, 0, 1], [0, 1, 0], 1.0, 0.0, 0.0, 0.0],
                "expected_outputs": {"0": [1.0, 0.0, 0.0]},
                "strict": True,
            },
        ],
        [
            {
                "inputs": [[1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 0, 0], 0.0, 0.0, 0.0, 0.0],
                "expected_outputs": {"0": [1.0, 0.0, 0.0]},
                "strict": False,
            },
        ],
    )

    T(
        "N12",
        "L2",
        "QUEST K-matrix assembly",
        "SatQuestKNode",
        "组装 4×4 对称 K（与 numpy 参考一致）。",
        [{"label": "b1", "type": "data"}, {"label": "r1", "type": "data"}, {"label": "a1", "type": "data"}],
        [{"label": "K_flat", "type": "data"}],
        "Single observation n=1. Build B=a1*outer(b1,r1), z=a1*cross(b1,r1), S=B+B.T, sig=trace(B), "
        "K[0,0]=sig; K[0,1:]=z; K[1:,0]=z; K[1:,1:]=S-sig*I. Output K_flat row-major 16.",
        ["satellite", "quest"],
        [
            {
                "inputs": [[1, 0, 0], [1, 0, 0], 1.0],
                "expected_outputs": {"0": k_n1},
                "strict": True,
            },
        ],
        [
            {
                "inputs": [[1, 0, 0], [0, 1, 0], 1.0],
                "expected_outputs": {"0": k_n1_orth},
                "strict": True,
            },
        ],
    )

    bce_val = math.log(2)  # mean BCE one element y=1 logit=0
    T(
        "N13",
        "L2",
        "TF binary cross-entropy (from logits)",
        "SatTfBceNode",
        "TensorFlow：二元交叉熵标量。",
        [{"label": "logits", "type": "data"}, {"label": "targets", "type": "data"}],
        [{"label": "loss", "type": "data"}],
        "import tensorflow as tf. logits/targets rank-1 lists same length. loss = mean(tf.nn.sigmoid_cross_entropy_with_logits(labels=targets, logits=logits)). Output Python float (e.g. float(loss.numpy())).",
        ["tensorflow", "loss"],
        [
            {
                "inputs": [[0.0], [1.0]],
                "expected_outputs": {"0": bce_val},
                "strict": False,
            },
        ],
        [
            {
                "inputs": [[0.0, 0.0], [1.0, 0.0]],
                "expected_outputs": {"0": bce_val},
                "strict": False,
            },
        ],
        acceptance_note="Requires tensorflow installed. strict:false for float noise.",
    )

    T(
        "N14",
        "L2",
        "TF dense linear layer",
        "SatTfDenseNode",
        "TensorFlow：线性层 y = x @ W.T + b。",
        [{"label": "x", "type": "data"}, {"label": "W_flat", "type": "data"}, {"label": "b", "type": "data"}],
        [{"label": "y", "type": "data"}],
        "x length-2 row vector, W_flat 4 floats row-major 2x2, b length-2. y = x @ W.T + b as Python list of floats.",
        ["tensorflow", "linear"],
        [
            {
                "inputs": [[2.0, 3.0], [1, 0, 0, 1], [0.0, 0.0]],
                "expected_outputs": {"0": [2.0, 3.0]},
                "strict": False,
            },
        ],
        [
            {
                "inputs": [[1.0, 0.0], [1, 0, 0, 1], [0.5, -0.5]],
                "expected_outputs": {"0": [1.5, -0.5]},
                "strict": False,
            },
        ],
        acceptance_note="Requires tensorflow.",
    )

    T(
        "N15",
        "L2",
        "PyTorch ReLU",
        "SatTorchReluNode",
        "PyTorch ReLU 前向。",
        [{"label": "x", "type": "data"}],
        [{"label": "y", "type": "data"}],
        "import torch. y = torch.relu(torch.tensor(x, dtype=torch.float32)).tolist()",
        ["pytorch", "activation"],
        [
            {"inputs": [[-1.0, 2.0, 0.0]], "expected_outputs": {"0": [0.0, 2.0, 0.0]}, "strict": False},
        ],
        [
            {"inputs": [[1.0, -2.0]], "expected_outputs": {"0": [1.0, 0.0]}, "strict": False},
        ],
        acceptance_note="Requires torch. Flatten nested list inputs in core_logic if needed.",
    )

    T(
        "N16",
        "L2",
        "PyTorch softmax",
        "SatTorchSoftmaxNode",
        "PyTorch softmax(dim)。",
        [{"label": "x", "type": "data"}, {"label": "dim", "type": "data"}],
        [{"label": "p", "type": "data"}],
        "import torch. dim=int(dim). p = torch.softmax(torch.tensor(x,float), dim=dim).tolist()",
        ["pytorch", "activation"],
        [
            {
                "inputs": [[1.0, 1.0], 0],
                "expected_outputs": {"0": [0.5, 0.5]},
                "strict": False,
            },
        ],
        [
            {
                "inputs": [[0.0, 0.0, 0.0], 0],
                "expected_outputs": {"0": [1 / 3, 1 / 3, 1 / 3]},
                "strict": False,
            },
        ],
        acceptance_note="Requires torch.",
    )

    # --- L3 ---
    eye9 = [1, 0, 0, 0, 1, 0, 0, 0, 1]
    T(
        "N17",
        "L3",
        "Full TRIAD attitude DCM",
        "SatTriadFullNode",
        "TRIAD 双矢量定姿 DCM（行主序）。",
        [
            {"label": "b1", "type": "data"},
            {"label": "b2", "type": "data"},
            {"label": "r1", "type": "data"},
            {"label": "r2", "type": "data"},
        ],
        [{"label": "R_flat", "type": "data"}],
        "Noiseless: b1=r1=[1,0,0], b2=r2=[0,1,0] implies R=I. Implement Black TRIAD so R @ b_hat ~ r_hat; output R_flat row-major I for this case.",
        ["satellite", "triad"],
        [
            {
                "inputs": [[1, 0, 0], [0, 1, 0], [1, 0, 0], [0, 1, 0]],
                "expected_outputs": {"0": eye9},
                "strict": False,
            },
        ],
        [
            {
                "inputs": [[1, 0, 0], [0, 1, 0], [0, 1, 0], [-1, 0, 0]],
                "expected_outputs": {"0": [0, -1, 0, 1, 0, 0, 0, 0, 1]},
                "strict": False,
            },
        ],
        acceptance_note="Second case: 90° about +z (noiseless); strict:false for numerical variation.",
    )

    T(
        "N18",
        "L3",
        "QUEST eigen quaternion",
        "SatQuestQNode",
        "QUEST：K 矩阵 + 最大特征值特征向量 → 单位四元数。",
        [{"label": "b1", "type": "data"}, {"label": "r1", "type": "data"}, {"label": "a1", "type": "data"}],
        [{"label": "q", "type": "data"}],
        "n=1. Build K same as N12. q = eigenvector for largest eigenvalue of K (numpy.linalg.eigh); normalize to unit length. Sign: match positive w if possible.",
        ["satellite", "quest"],
        [
            {
                "inputs": [[1, 0, 0], [1, 0, 0], 1.0],
                "expected_outputs": {"0": q_n18},
                "strict": False,
            },
        ],
        [
            {
                "inputs": [[1, 0, 0], [1, 0, 0], 1.0],
                "expected_outputs": {"0": q_n18},
                "strict": False,
            },
        ],
        acceptance_note="Eigenvector sign non-unique; strict:false. Requires numpy.",
    )

    T(
        "N19",
        "L3",
        "TF one SGD step",
        "SatTfSgdStepNode",
        "TensorFlow 单步梯度下降。",
        [{"label": "x", "type": "data"}, {"label": "y", "type": "data"}, {"label": "w", "type": "data"}, {"label": "b", "type": "data"}, {"label": "eta", "type": "data"}],
        [{"label": "w_new", "type": "data"}, {"label": "b_new", "type": "data"}],
        "L = (y - w*x - b)**2 scalars. One step w -= eta*grad_w, b -= eta*grad_b with GradientTape. x=1,y=1,w=0,b=0,eta=0.1 -> w_new=0.2, b_new=0.2.",
        ["tensorflow", "optim"],
        [
            {
                "inputs": [1.0, 1.0, 0.0, 0.0, 0.1],
                "expected_outputs": {"0": 0.2, "1": 0.2},
                "strict": False,
            },
        ],
        [
            {
                "inputs": [1.0, 2.0, 0.0, 0.0, 0.1],
                "expected_outputs": {"0": 0.4, "1": 0.2},
                "strict": False,
            },
        ],
        acceptance_note="Requires tensorflow. Gradients dL/dw = -2*x*(y-w*x-b), dL/db = -2*(y-w*x-b).",
    )

    T(
        "N20",
        "L3",
        "PyTorch BN+MLP inference",
        "SatTorchBnMlpNode",
        "PyTorch 两层 MLP + BN 推理。",
        [{"label": "x", "type": "data"}],
        [{"label": "logits", "type": "data"}],
        "import torch.nn as nn. Fixed 2->2->2 MLP: Linear(2,2), BatchNorm1d(2), ReLU, Linear(2,2). "
        "Use eval(); running_mean=0, running_var=1, gamma=1, beta=0, weights I and zero bias where possible; "
        "input x length-2 -> logits list length-2. Document parameters inside core_logic.",
        ["pytorch", "mlp"],
        [
            {"inputs": [[0.0, 0.0]], "expected_outputs": {"0": [0.0, 0.0]}, "strict": False},
        ],
        [
            {"inputs": [[1.0, -1.0]], "expected_outputs": {"0": [0.0, 0.0]}, "strict": False},
        ],
        acceptance_note="Exact logits depend on BN eps and default Linear init; stub uses strict:false — tighten in custom harness if needed.",
    )

    payload = {
        "schema_version": "node_tasks_bench_sat_ml_v1",
        "source_md": "scripts/evaluation/data/node_tasks_bench_sat_ml_en.md",
        "description": doc,
        "tasks": tasks,
    }

    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Wrote", out_path, "tasks", len(tasks))


if __name__ == "__main__":
    main()
