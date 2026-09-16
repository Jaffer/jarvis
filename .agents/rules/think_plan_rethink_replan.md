# Pre-Planning Routine: Think, Plan, Rethink, Replan

Before creating or updating an implementation plan (`implementation_plan.md`), the agent must always execute the following mandatory 4-step thinking routine:

1. **Think**:
   - Deeply analyze the problem, requirements, codebase dependencies, hardware/OS constraints, and potential edge cases.
   - Uncover underlying root causes rather than treating surface symptoms.

2. **Plan**:
   - Formulate the preliminary technical architecture, component breakdown, interfaces, and testing strategy.

3. **Rethink**:
   - Actively and critically stress-test the initial plan:
     - Identify where the plan will break, lock threads, introduce race conditions, or fail under stress.
     - Question all assumptions regarding libraries, external APIs, and hardware availability.
     - Identify risks to existing features and backward compatibility.

4. **Replan**:
   - Redesign and harden the architecture to eliminate every discovered flaw.
   - Incorporate defensive fallbacks, non-blocking asynchronous patterns, adaptive thresholds, and atomic state handling.

5. **Draft Implementation Plan**:
   - Only after successfully passing through Think -> Plan -> Rethink -> Replan, synthesize the finalized architecture into `implementation_plan.md` for user approval.
