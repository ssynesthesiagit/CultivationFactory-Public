// API-shaped fixture; test_sol69_objects.py checks authoritative resolution.
export const durability = {
  presets: {door: {hp: 18, ac: 15, size: 'medium', resilient: true}, custom: {hp: 18, ac: 15, size: 'medium', resilient: true}},
  materials: {wood: 15, iron: 19},
  sizes: {medium: {'0': 4, '1': 18}, small: {'0': 3, '1': 10}},
};
