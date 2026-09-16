# Workspace Rules: J.A.R.V.I.S.

## Mandatory Pre-Planning Discipline: Think, Plan, Rethink, Replan

Before creating or updating any implementation plan, the agent MUST strictly execute the **Think, Plan, Rethink, Replan** cycle:

1. **Think**:
   - Deeply examine user requirements, active codebase architecture, hardware/OS constraints, and failure modes.
   - Analyze root causes and edge cases rather than jumping to superficial solutions.

2. **Plan**:
   - Construct the initial technical design, component boundaries, data flow, and verification strategy.

3. **Rethink**:
   - Rigorously challenge the initial design:
     - Where could this design fail under real-world usage? (e.g., race conditions, hardware blocking, acoustic feedback, audio thread locks, API latencies)
     - What assumptions might be invalid?
     - What unintended side effects could impact existing features (biometrics, 3D constructs, Telegram, voice)?
     - Is the design truly movie-authentic, robust, and state of the art?

4. **Replan**:
   - Overcome every identified flaw with concrete engineering safeguards, defensive fallbacks, non-blocking asynchronous architectures, and adaptive thresholds.
   - Restructure the plan to be resilient, modular, and cleanly verifiable.

5. **Create Implementation Plan**:
   - Only after explicitly completing the Think -> Plan -> Rethink -> Replan analysis should `implementation_plan.md` be drafted and presented for user approval.
