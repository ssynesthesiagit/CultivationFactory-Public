// The map has no orientation field: east is +x, north is -y. Direction points toward the sky source.
const models = {
  dawn: {direction: [1, 0], length: 1.1, colour: "#f3a26d", strength: 0.85, grade: 0.13},
  day: {direction: [-Math.SQRT1_2, -Math.SQRT1_2], length: 0.35, colour: "#ffffff", strength: 1, grade: 0},
  dusk: {direction: [-1, 0], length: 1.1, colour: "#e88b61", strength: 0.85, grade: 0.15},
  night: {direction: [-Math.SQRT1_2, -Math.SQRT1_2], length: 0.6, colour: "#6689c2", strength: 0.18, grade: 0.14},
  underground: {direction: [0, 0], length: 0, colour: "#ffffff", strength: 0, grade: 0},
};
export function sky(timeOfDay) { return models[timeOfDay] || models.day; }
// Offset is opposite the direction of the light source, in units chosen by the caller.
export function skyOffset(model, scale = 1) {
  return model.direction.map(value => -value * model.length * scale);
}
