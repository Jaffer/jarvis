import { createGevActionRunner } from './gevActions.js';
import { createVoiceCommands } from './commands.js';
export * from './realtimeController.js';

/**
 * Compose the standalone action runner with the voice controls.
 *
 * JARVIS vendored delta: the runner is also published on the debug handle as
 * `runAction`, so the JARVIS bridge can drive the globe programmatically. The
 * globe keeps no brain of its own — JARVIS decides, the globe executes.
 */
export function initGevVoiceCommands(options) {
  const runner = createGevActionRunner(options);
  if (typeof window !== 'undefined' && window.__godsEyeView) {
    window.__godsEyeView.runAction = runner;
  }
  const voice = { ...options, runner };
  return createVoiceCommands(voice);
}
