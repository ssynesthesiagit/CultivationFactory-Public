// Original procedural ancient-China hip roofs; north-west light matches map art.
// No images or combat mechanics. Geometry is in board squares, independent of zoom.
export const EAVE = 0.18;
export function roofGeometry(region) {
  const xs = region.footprint.map(c => c[0]), ys = region.footprint.map(c => c[1]);
  const x = Math.min(...xs)-EAVE, y = Math.min(...ys)-EAVE;
  const w = Math.max(...xs)+1+EAVE-x, h = Math.max(...ys)+1+EAVE-y;
  const vertical = h > w, hip = Math.min(w,h)/2;
  const ridge = vertical ? [[x+w/2,y+hip],[x+w/2,y+h-hip]] : [[x+hip,y+h/2],[x+w-hip,y+h/2]];
  return {x, y, w, h, vertical, ridge};
}

function footprintPath(cells) {
  // Horizontal spans: O(rows), rather than one SVG element per map square.
  const rows = new Map();
  for (const [x,y] of cells) { if (!rows.has(y)) rows.set(y,[]); rows.get(y).push(x); }
  const paths = [];
  for (const [y,xs] of rows) {
    xs.sort((a,b)=>a-b);
    for (let i=0; i<xs.length;) {
      const start=xs[i]; let end=start; i++;
      while (i<xs.length && xs[i]===end+1) end=xs[i++];
      paths.push(`M${start-EAVE} ${y-EAVE}h${end-start+1+2*EAVE}v${1+2*EAVE}h${-(end-start+1+2*EAVE)}Z`);
    }
  }
  return paths.join('');
}

export function roofMarkup(region, style, id, openings = []) {
  const {x,y,w,h,vertical,ridge:[a,b]} = roofGeometry(region);
  const path = footprintPath(region.footprint), red = style === 'red';
  const tile = red ? '#964a39' : '#667077', dark = red ? '#542c29' : '#343c43';
  const corners = [[x,y],[x+w,y],[x+w,y+h],[x,y+h]];
  const hips = corners.map((c,i)=>[c, vertical ? (i<2?a:b) : ([0,3].includes(i)?a:b)]);
  const facet = points => `M${points.join('L')}Z`;
  const north = vertical ? [corners[0],corners[1],a] : [corners[0],corners[1],b,a];
  const east = vertical ? [corners[1],corners[2],b,a] : [corners[1],corners[2],b];
  const south = vertical ? [corners[2],corners[3],b] : [corners[2],corners[3],a,b];
  const apertures = (openings || []).filter(row => Number.isInteger(row.x) && Number.isInteger(row.y)
    && region.inside.has(`${row.x},${row.y}`) && ['trapdoor', 'skylight'].includes(row.kind));
  const clearCells = apertures.filter(row => row.open === true || row.kind === 'skylight')
    .map(row => `<rect x="${row.x}" y="${row.y}" width="1" height="1" fill="black"/>`).join('');
  const openingArt = apertures.map(row => {
    const open = row.open === true, glass = row.kind === 'skylight';
    const name = `${open ? 'Open' : 'Closed'} ${glass ? 'skylight' : 'trapdoor'}`;
    return `<g data-roof-opening="${row.x},${row.y}"><title>${name}${open ? ': passage through the roof' : glass ? ': glass blocks passage' : ': solid roof surface'}</title>`
      + `<rect x="${row.x + .04}" y="${row.y + .04}" width=".92" height=".92" rx=".04" fill="${open ? 'none' : glass ? '#a9e0ee' : '#655044'}" fill-opacity="${glass ? '.32' : '1'}" stroke="${open ? '#d0ba85' : '#ad926c'}" stroke-width=".08"/>`
      + (open ? '' : `<path d="M${row.x + .08} ${row.y + .5}h.84${glass ? `M${row.x + .5} ${row.y + .08}v.84` : ''}" stroke="#ad926c" stroke-width=".05"/>`) + '</g>';
  }).join('');
  return `<defs><clipPath id="${id}-clip"><path d="${path}"/></clipPath>
    <mask id="${id}-surface" maskUnits="userSpaceOnUse" x="${x - 1}" y="${y - 1}" width="${w + 2}" height="${h + 2}"><rect x="${x - 1}" y="${y - 1}" width="${w + 2}" height="${h + 2}" fill="white"/>${clearCells}</mask>
    <pattern id="${id}-tiles" width=".28" height=".24" patternUnits="userSpaceOnUse"${vertical?' patternTransform="rotate(90)"':''}>
      <rect width=".28" height=".24" fill="${tile}"/><path d="M0 .02H.28M.02 0V.24M.15 0V.24" fill="none" stroke="${dark}" stroke-width=".025"/>
      <path d="M.06 .02V.23M.19 .02V.23" stroke="#d5c6ac" stroke-opacity=".22" stroke-width=".018"/>
    </pattern><filter id="${id}-shadow" x="-10%" y="-10%" width="120%" height="120%"><feGaussianBlur stdDeviation=".07"/></filter></defs>
    <g mask="url(#${id}-surface)"><path d="${path}" fill="#080c11" opacity=".24" transform="translate(.13 .17)" filter="url(#${id}-shadow)"/>
    <g clip-path="url(#${id}-clip)"><rect x="${x}" y="${y}" width="${w}" height="${h}" fill="url(#${id}-tiles)"/>
    <path d="${facet(north)}" fill="#fff1ca" opacity=".12"/>
    <path d="${facet(east)}" fill="#111820" opacity=".22"/>
    <path d="${facet(south)}" fill="#111820" opacity=".16"/>
    <path d="${hips.map(([c,r])=>`M${c}L${r}`).join('')}M${a}L${b}" fill="none" stroke="${dark}" stroke-width=".14" stroke-linecap="round"/>
    <path d="${hips.map(([c,r])=>`M${c}L${r}`).join('')}M${a}L${b}" fill="none" stroke="#c6bda8" stroke-opacity=".48" stroke-width=".04" stroke-linecap="round"/>
    </g></g>${openingArt}`;
}
