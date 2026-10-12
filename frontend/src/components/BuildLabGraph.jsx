import { useId, useMemo, useState } from 'react'
import { buildLabLayout } from '../utils/buildLabLayout'

// Geometry represents recorded relationships only. Light trails express activity,
// not optimizer iterations, probability, or a simulated search through combinations.
export default function BuildLabGraph({ elements, t, onInspect, motion }) {
    const prefix = useId().replace(/:/g, '')
    const { nodes, paths, clusters } = useMemo(() => buildLabLayout(elements), [elements])
    const [focused, setFocused] = useState(null)
    const [zoom, setZoom] = useState(1)
    const linked = new Set(paths.filter(p => p.source === focused || p.target === focused).flatMap(p => [p.source, p.target]))
    const trim = (s, n = 23) => s?.length > n ? `${s.slice(0, n - 1)}…` : s
    return <div className="build-lab-network">
        <div className="build-lab-zoom">
            <button type="button" aria-label={t('build_map_zoom_in')} onClick={() => setZoom(z => Math.min(1.8, z + .2))}>+</button>
            <button type="button" aria-label={t('build_map_zoom_out')} onClick={() => setZoom(z => Math.max(1, z - .2))}>−</button>
        </div>
        <svg className="build-map-graph" viewBox={`${500 - 500 / zoom} ${300 - 300 / zoom} ${1000 / zoom} ${600 / zoom}`}
            role="img" aria-label={t('build_map_graph')}>
            <defs>
                <radialGradient id={`${prefix}-core`}><stop stopColor="#baffef"/><stop offset=".65" stopColor="#43deb4"/><stop offset="1" stopColor="#1b6c66"/></radialGradient>
                <radialGradient id={`${prefix}-point`}><stop stopColor="#d9f0ff"/><stop offset=".45" stopColor="#87bde1"/><stop offset="1" stopColor="#315974"/></radialGradient>
                <radialGradient id={`${prefix}-gold`}><stop stopColor="#fff9ce"/><stop offset=".5" stopColor="#f7cb70"/><stop offset="1" stopColor="#9d6627"/></radialGradient>
                <radialGradient id={`${prefix}-saved`}><stop stopColor="#dcffed"/><stop offset=".5" stopColor="#6ed5aa"/><stop offset="1" stopColor="#286e58"/></radialGradient>
                <filter id={`${prefix}-light`} x="-100%" y="-100%" width="300%" height="300%"><feGaussianBlur stdDeviation="3"/></filter>
            </defs>
            <g className="build-lab-orbits" aria-hidden="true">
                <ellipse cx="500" cy="550" rx="180" ry="17"/><ellipse cx="500" cy="550" rx="250" ry="26"/>
                {clusters.map((c, i) => <g key={i}><ellipse cx={c.x} cy={c.y} rx={c.rx} ry={c.ry}/>
                    <text x={c.x} y={c.y - c.ry - 24}>{c.label || t('build_map_candidates')}</text>
                    <text x={c.x} y={c.y - c.ry - 8} className="build-lab-cluster-count">{c.count} · {c.selectedCount} {t('build_map_selected_short')}</text></g>)}
            </g>
            <g fill="none" aria-hidden="true">
                {paths.filter(p => p.selected && [p.source, p.target].includes(focused)).map(p => <path key={`halo-${p.id}`} d={p.d} stroke="#ffc861" strokeWidth="4" opacity=".3" filter={`url(#${prefix}-light)`}/>)}
                {paths.map(p => <path key={p.id} d={p.d} data-reveal-step={p.kind === 'profile' ? 1 : p.kind === 'placement' ? 3 : 2} className={`lab-link${p.selected ? ' is-selected' : ''}${[p.source, p.target].includes(focused) ? ' is-highlighted' : ''}${p.kind === 'prerequisite' ? ' is-prerequisite' : ''}`}
                    style={{ opacity: focused && ![p.source, p.target].includes(focused) ? .1 : undefined }}/>) }
            </g>
            {motion && <g className="build-lab-trails" aria-hidden="true">{paths.filter(p => p.flow).map((p, i) => <g key={p.id}>
                {[0, 1, 2].map(j => <circle key={j} r={j ? 1.7 : 3} fill={p.selected ? '#ffe9a9' : '#b5e8ff'} opacity={1 - j * .3}>
                    <animateMotion path={p.d} dur={`${3.2 + i % 4 * .45}s`} begin={`${-(i * .23 + j * .09)}s`} repeatCount="indefinite"/>
                </circle>)}
            </g>)}</g>}
            {nodes.map(n => {
                const profile = n.state === 'profile', outcome = n.state === 'outcome', semester = n.state === 'semester'
                const color = profile ? 'core' : n.state === 'published' ? 'saved' : n.selected ? 'gold' : 'point'
                const radius = profile ? 21 : outcome ? 8 : n.selected ? 6 : 4
                return <g key={n.id} className="lab-node" data-reveal-step={n.revealStep} transform={`translate(${n.x}, ${n.y})`}
                    role={profile ? undefined : 'button'} tabIndex={profile ? undefined : 0}
                    aria-label={profile ? undefined : n.label} onClick={() => onInspect(n)}
                    onKeyDown={e => { if (['Enter', ' '].includes(e.key)) { e.preventDefault(); onInspect(n) } }}
                    onMouseEnter={() => setFocused(n.id)} onMouseLeave={() => setFocused(null)}
                    onFocus={() => setFocused(n.id)} onBlur={() => setFocused(null)}
                    style={{ opacity: focused && focused !== n.id && !linked.has(n.id) ? .25 : 1 }}>
                    <title>{profile ? t('build_map_goal') : n.label}{n.detail ? ` — ${n.detail}` : ''}</title>
                    {profile ? <><circle r="33" fill="#2ccd9e12"/><circle r="27" fill="none" stroke="#54eab4" strokeWidth="1"/>
                        <circle r={radius} fill={`url(#${prefix}-${color})`}/>
                        <path d="M-8 8V-8H1V8M1-3H8V8M-5-4H-2M-5 0H-2M-5 4H-2M4 1H6M4 5H6" fill="none" stroke="#053e35" strokeWidth="1.7"/>
                    </> : semester ? <rect x="-24" y="-13" width="48" height="26" rx="3" fill="#15374a" stroke="#5189a6"/>
                        : <><circle r={radius + 3} fill="none" stroke={n.selected ? '#b08748' : '#335c77'} opacity=".7"/>
                            <circle r={radius} fill={`url(#${prefix}-${color})`}/></>}
                    {(profile || outcome || semester || n.showLabel || focused === n.id || n.state === 'aggregate') &&
                        <text y={semester ? 4 : profile ? 41 : outcome ? 25 : -14} className={n.selected ? 'is-selected' : ''}>
                            {profile ? t('build_map_goal') : trim(n.label, outcome ? 14 : semester ? 6 : 23)}</text>}
                </g>
            })}
        </svg>
    </div>
}
