# Node authoring benchmark (20 tasks · satellite attitude · TensorFlow · PyTorch)

> **Purpose**: Task specification (“source of truth”) for thesis evaluation experiments. Each entry defines **functional requirements and acceptance criteria** only. **Port count, labels, types (`data`/`exec`), widgets, and concrete `core_logic`** are produced under your chosen workflow (manual / Generator / AI).  
> **Difficulty bands** (aligned with `GENERATOR_EVALUATION_STRATEGY.md`): **L1 = N01–N08**, **L2 = N09–N16**, **L3 = N17–N20**.  
> **L3 anchors**: classical **TRIAD** and **QUEST (q-method)** attitude determination; plus advanced **TensorFlow / PyTorch** nodes.

---

## General conventions (put in the experimental protocol)

1. **Numeric types**: Vectors are **3×1** or length-3 iterables unless stated otherwise; matrices are **3×3** unless stated otherwise. Pick and document one **quaternion layout** in the node (e.g. Hamilton \(q = [q_0, q_1, q_2, q_3]\)).  
2. **Frames**: Tasks require **body-frame** and **reference-frame** observations in pairs; whether reference is ECI, orbit, NED, etc. must be stated consistently in the node `description`.  
3. **Ports**: Unless noted, **no fixed port count**; you must design `inputs`/`outputs` from algorithm I/O and keep the node **wirable and runnable in Ryven**.  
4. **Libraries**: `numpy` allowed; **TensorFlow / PyTorch** only where the task says so; satellite tasks may use `numpy`/`math` unless otherwise specified.  
5. **Acceptance**: Each task lists **minimum functional checks**; full studies may add stubs, unit tests, and Ryven load checks.

---

# L1 — Foundational but attitude / learning themed (N01–N08)

### N01 — Body-frame observation normalization (Sun / direction)

**Requirements**: Input is a raw sensor direction vector (possibly noisy, non-unit). Output is a **unit direction** (L2 norm 1). Zero or invalid inputs must follow a documented sentinel policy (e.g. zero vector or `None` wrapped in `Data`).

**Ports**: You design (e.g. raw 3-vector; optional scalar gain).

**Acceptance**: At least three non-collinear cases; output norm error \(< 10^{-6}\) in floating-point sense.

---

### N02 — Geomagnetic field magnitude and unit vector

**Requirements**: Input is three-axis magnetometer reading \(\mathbf{b}\) in body frame. Output **\(\|\mathbf{b}\|\)** and **unit vector** \(\hat{\mathbf{b}}\). Division by zero / bad inputs must be handled explicitly.

**Ports**: You design.

**Acceptance**: Match `numpy.linalg.norm`; unit vector dotted with itself is 1.

---

### N03 — Angle between two 3D vectors (radians)

**Requirements**: Inputs are two 3D vectors (need not be unit). Output **included angle** in \([0,\pi]\) radians. Handle degeneracy (parallel / anti-parallel / zero).

**Ports**: You design.

**Acceptance**: Match `numpy.arccos(numpy.clip(dot, -1, 1))` within tolerance.

---

### N04 — Cross product and scalar triple product (optional)

**Requirements**: Inputs \(\mathbf{a},\mathbf{b}\in\mathbb{R}^3\). Output \(\mathbf{a}\times\mathbf{b}\). Optionally also output scalar \(\mathbf{c}\cdot(\mathbf{a}\times\mathbf{b})\) for coplanarity (your choice: one or two data outputs).

**Ports**: You design.

**Acceptance**: Match `numpy.cross`; numerically verify \(\mathbf{c}\perp\mathbf{a}\) and \(\mathbf{c}\perp\mathbf{b}\).

---

### N05 — Quaternion conjugate

**Requirements**: Input quaternion \(q\) (format fixed in node docs). Output **conjugate** \(q^*\).

**Ports**: You design (four scalars or another representation the generator can express).

**Acceptance**: At least check real part of \(q \otimes q^*\) vs identity when \(q\) is unit.

---

### N06 — Quaternion normalization

**Requirements**: Input any non-zero quaternion; output **unit quaternion**. Zero input: documented behavior.

**Ports**: You design.

**Acceptance**: Output norm (per your quaternion norm definition) is 1.

---

### N07 — Single-step angular-rate integration (quaternion)

**Requirements**: Inputs: current quaternion \(q_k\), body angular rate \(\boldsymbol{\omega}\), step \(\Delta t\). Output **one-step** \(q_{k+1}\) using the discretization you document (e.g. first-order exponential map / small-angle approximation).

**Ports**: You design.

**Acceptance**: For \(\Delta t=0\), output matches \(q_k\) within numerical tolerance.

---

### N08 — Gyro bias correction

**Requirements**: Inputs raw rate \(\boldsymbol{\omega}_{raw}\) and bias estimate \(\mathbf{b}_g\). Output \(\boldsymbol{\omega}_{corr}=\boldsymbol{\omega}_{raw}-\mathbf{b}_g\). Optional saturation.

**Ports**: You design.

**Acceptance**: At least one hand-checked vector subtraction.

---

# L2 — Intermediate: multiple inputs, matrices/tensors, TF, attitude geometry (N09–N16)

### N09 — DCM and vector projection

**Requirements**: Input **3×3** rotation \(\mathbf{R}\) (body→reference **or** reference→body—**declare in the node**) and body vector \(\mathbf{v}_b\). Output reference-frame vector \(\mathbf{v}_r=\mathbf{R}\mathbf{v}_b\) (or the opposite if you declared the inverse convention).

**Ports**: You design (matrix as nine scalars or another convention consistent with the generator).

**Acceptance**: Match `numpy` matrix–vector multiply.

---

### N10 — TRIAD (**partial**: orthonormal basis only)

**Requirements**: Given two **non-collinear** observation pairs: body \(\hat{\mathbf{b}}_1,\hat{\mathbf{b}}_2\) and reference \(\hat{\mathbf{r}}_1,\hat{\mathbf{r}}_2\) (unitize inside the node if needed). Following TRIAD-style construction, build a **third orthonormal axis** (e.g. \(\hat{\mathbf{t}}_1=\hat{\mathbf{b}}_1\), \(\hat{\mathbf{t}}_2 \propto \hat{\mathbf{b}}_1\times\hat{\mathbf{b}}_2\), \(\hat{\mathbf{t}}_3=\hat{\mathbf{t}}_1\times\hat{\mathbf{t}}_2\)). Output **3×3 orthonormal** \(\mathbf{T}_b=[\hat{\mathbf{t}}_1\ \hat{\mathbf{t}}_2\ \hat{\mathbf{t}}_3]\) or equivalent three columns.

**Note**: This is a **TRIAD precursor**; full \(\mathbf{R}\) is **not** required.

**Ports**: You design.

**Acceptance**: Columns mutually orthogonal within tolerance; each column unit length.

---

### N11 — Weighted vector observation fusion (algebraic mean direction)

**Requirements**: Inputs: \(N\) unit directions \(\{\hat{\mathbf{v}}_i\}\) and weights \(\{w_i\}\) (\(N\) and wiring are your choice; \(N\ge 3\) is recommended). Output **unit** direction proportional to \(\sum w_i \hat{\mathbf{v}}_i\). All-zero weights: defined behavior.

**Ports**: You design (e.g. fix \(N=4\) to simplify).

**Acceptance**: Single weight 1 and others 0 reproduces that direction.

---

### N12 — QUEST / q-method **K-matrix assembly**

**Requirements**: Given \(n\) observation sets: body unit \(\hat{\mathbf{b}}_i\), reference unit \(\hat{\mathbf{r}}_i\), scalar weight \(a_i\) (\(i=1..n\); \(n\) may be fixed e.g. 3 or 4). Build the **4×4 matrix \(\mathbf{K}\)** (or equivalent **B** form—**state symbol convention in the node**). **No eigen solve** in this task—only output the symmetric matrix (16 scalars or structured).

**References**: Shuster & Oh, QUEST; Markley & Crassidis (K-matrix construction).

**Ports**: You design.

**Acceptance**: For \(n=1\), \(a_1=1\), matrix is symmetric; spot-check entries against a small hand calculation.

---

### N13 — TensorFlow: **sigmoid + binary cross-entropy** (element-wise path to scalar)

**Requirements**: Use **TensorFlow**. Inputs: logits tensor and target tensor (shapes documented: broadcastable or identical). Output a **scalar** BCE (fix **mean** vs **sum** in the node).

**Ports**: You design (rank-1 tensors allowed to reduce difficulty).

**Acceptance**: Close to `tf.keras.losses.BinaryCrossentropy(from_logits=True)` on the same tensors (relative error threshold).

---

### N14 — TensorFlow: **Dense forward** (no training)

**Requirements**: Use **TensorFlow**. Inputs \(\mathbf{x}\), weight matrix \(\mathbf{W}\), bias \(\mathbf{b}\). Output \(\mathbf{y}=\mathbf{x}\mathbf{W}^T+\mathbf{b}\) (or layout you document). Fix one shape convention (e.g. batch × in_features).

**Ports**: You design.

**Acceptance**: Match `tf.linalg.matmul` + `tf.add`.

---

### N15 — PyTorch: **ReLU forward**

**Requirements**: Use **PyTorch**. Input tensor `x`, output `torch.relu(x)`. Preserve `dtype` / `device` with input (CPU is enough).

**Ports**: You design.

**Acceptance**: Element-wise match `torch.relu`.

---

### N16 — PyTorch: **Softmax (given dim)**

**Requirements**: Use **PyTorch**. Input tensor and integer `dim`, output `torch.softmax(x, dim=dim)`. Out-of-range `dim`: error or documented fallback.

**Ports**: You design.

**Acceptance**: Along softmax dim, sums to 1 within tolerance.

---

# L3 — Advanced: full TRIAD / QUEST + deep-learning nodes (N17–N20)

### N17 — **Full TRIAD**: two-vector attitude

**Requirements**: Inputs: two unit observation pairs \((\hat{\mathbf{b}}_1,\hat{\mathbf{r}}_1)\), \((\hat{\mathbf{b}}_2,\hat{\mathbf{r}}_2)\); assume directions are **not collinear**. Using **TRIAD (Black)**, build rotation \(\mathbf{R}\) such that \(\hat{\mathbf{b}}_i \approx \mathbf{R}^T \hat{\mathbf{r}}_i\) **or** \(\hat{\mathbf{r}}_i \approx \mathbf{R}\hat{\mathbf{b}}_i\)—**pick one convention in the node and use it consistently**. Output **3×3 DCM** and/or **quaternion** (your design, but self-consistent).

**Ports**: Fully your design.

**Acceptance**:  
- Noiseless synthetic data: build body observations from a known \(\mathbf{R}\), recover \(\mathbf{R}\) with Frobenius or quaternion angular error below threshold.  
- Collinear / degenerate inputs: explicit behavior (error / sentinel).

---

### N18 — **QUEST (q-method)**: weighted multi-vector → optimal unit quaternion

**Requirements**: Inputs: \(n\ge 2\) weighted sets \((\hat{\mathbf{b}}_i,\hat{\mathbf{r}}_i,a_i)\). Build **\(\mathbf{K}\)** (same convention as N12). **Solve** for the **maximum-eigenvalue eigenvector** and map to a **unit quaternion** \(\mathbf{q}\) optimal in the Wahba / QUEST sense (one-sentence citation in the node).

**Implementation note (non-unique)**: e.g. `numpy.linalg.eigh` on \(\mathbf{K}\), take eigenvector for largest eigenvalue, map to quaternion; fix sign ambiguity with a rule.

**Ports**: Fully your design (fix \(n=3\) or \(4\) if simpler).

**Acceptance**:  
- At least two synthetic cases: known quaternion generates observations; reconstructed quaternion angular error below threshold.  
- All-zero weights or degenerate inputs: defined behavior.

---

### N19 — TensorFlow: **one gradient-descent step** (explicit gradients)

**Requirements**: Use **TensorFlow**. Given scalar loss \(L\), small set of trainable variables (e.g. scalars \(w,b\)) and learning rate \(\eta\), perform **one** update \(\theta \leftarrow \theta - \eta \nabla_\theta L\) (e.g. `tf.GradientTape`). Output updated values (or new tensors).

**Ports**: You design (simple 1D linear-regression loss \(L=(y-wx-b)^2\) is recommended).

**Acceptance**: Matches one manual step or one `tf.keras.optimizers.SGD` step within tolerance.

---

### N20 — PyTorch: **BatchNorm MLP block forward** (inference)

**Requirements**: Use **PyTorch**. Two layers: Linear → BatchNorm1d → ReLU → Linear. **Inference** semantics (`eval()`): use **running mean/variance** or supply them as inputs. Input: batch feature matrix; output: logits. Forward must be correct; no requirement to export autograd state outside the node.

**Ports**: You design (`gamma`, `beta`, `running_mean`, `running_var` as ports **or** fixed inside `core_logic`—if fixed, state that explicitly).

**Acceptance**: Match an `nn.Sequential` with the same structure in `eval()` within tolerance.

---

## Appendix: mapping to experiment CSV `task_id`

| task_id | band | Domain |
|---------|------|--------|
| N01–N08 | L1 | Vectors / quaternions / gyro basics |
| N09–N12 | L2 | Attitude geometry + QUEST matrix assembly |
| N13–N16 | L2 | TensorFlow / PyTorch core ops |
| N17–N18 | L3 | Full TRIAD / QUEST |
| N19–N20 | L3 | TF one-step optim / PyTorch BN+MLP inference |

---

*File path: `scripts/evaluation/data/node_tasks_bench_sat_ml_en.md`*
