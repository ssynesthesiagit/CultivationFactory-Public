// A decision's saved answer keys identify it across clients and table refreshes.
// Prompt wording is included so a changed set of choices supersedes the old one.
export function decisionKey(prompt) {
  if (!prompt) return "";
  return JSON.stringify([prompt.context, prompt.choice || null, prompt.trigger || prompt.moment || ""]);
}

export function decisionChanged(prompt, pending) {
  return decisionKey(prompt) !== decisionKey(pending?.reaction);
}
