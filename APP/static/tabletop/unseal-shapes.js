// Decode sealed map geometry for both table and player boards.
export function unsealShapes(table) {
  const scale = table.scale || 1;
  const featureScale = table.feature_scale || scale;
  return {
    walls: (table.walls || []).map(wall => ({...wall, points: wall.points.map(([x, y]) => [x / scale, y / scale])})),
    features: (table.features || []).map(feature => ({
      ...feature,
      ...Object.fromEntries(['area', 'path'].filter(key => feature[key])
        .map(key => [key, feature[key].map(([x, y]) => [x / featureScale, y / featureScale])])),
      ...(feature.width != null ? {width: feature.width / featureScale} : {}),
    })),
  };
}
