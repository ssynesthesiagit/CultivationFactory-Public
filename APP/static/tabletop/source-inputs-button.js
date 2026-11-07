// The Game Master's private-declaration entry follows the availability that already rides with the fight state
// (state.source_inputs_available, counted from the same plug-in forms the declaration dialog lists). Drawing the
// toolbar therefore reads nothing: the entry never asks the /source-inputs endpoint itself, so an unchanged poll
// costs no extra request. After a declaration is saved the next state carries the new availability.
// `allowed` keeps the owner's declarations to the Game Master view (as the GM scene control is): no GM view, no entry.
export function sourceInputsButton({button, allowed = () => true}) {
  return available => {
    button.hidden = button.disabled = !available || !allowed();
  };
}
