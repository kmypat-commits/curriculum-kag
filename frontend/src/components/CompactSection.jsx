/** Accessible compact disclosure used by dense curriculum-analysis pages. */
export default function CompactSection({
    title,
    subtitle,
    accent = '#366092',
    defaultOpen = false,
    toggleLabel = 'Open / collapse',
    children,
}) {
    return <details
        className="card"
        open={defaultOpen}
        style={{ marginBottom: 20, borderLeft: `5px solid ${accent}`, padding: 0, overflow: 'hidden' }}
    >
        <summary style={{ cursor: 'pointer', listStyle: 'none', padding: '14px 18px', display: 'flex', justifyContent: 'space-between', gap: 14, alignItems: 'center', background: '#fbfdff' }}>
            <span>
                <span style={{ display: 'block', fontWeight: 800, color: '#17233b' }}>{title}</span>
                {subtitle && <span style={{ display: 'block', marginTop: 3, fontSize: 12, color: '#667085', fontWeight: 400 }}>{subtitle}</span>}
            </span>
            <span style={{ fontSize: 12, color: '#667085', whiteSpace: 'nowrap' }}>{toggleLabel}</span>
        </summary>
        <div style={{ padding: 18 }}>{children}</div>
    </details>
}
