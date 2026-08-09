export default function PlanBuildProgress({
    active,
    progress,
    status,
    title,
    stageLabel,
    stageDetail,
    elapsedLabel,
    longRunningHint,
}) {
    if (!active) return null

    const safeProgress = Math.max(0, Math.min(100, Number(progress) || 0))
    return (
        <div className="card" style={{ marginBottom: '20px', borderLeft: '5px solid #366092' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: '16px', alignItems: 'center' }}>
                <div>
                    <h3 style={{ margin: '0 0 6px' }}>{title}</h3>
                    <div style={{ color: '#566', fontSize: 14 }}>{stageLabel(status.stage)}</div>
                    {stageDetail && <div style={{ color: '#789', fontSize: 13, marginTop: 4 }}>{stageDetail}</div>}
                    {elapsedLabel && <div style={{ color: '#789', fontSize: 13, marginTop: 4 }}>{elapsedLabel}</div>}
                </div>
                <strong style={{ fontSize: 22, color: '#366092' }}>{safeProgress}%</strong>
            </div>
            <div style={{ height: 10, background: '#e8edf5', borderRadius: 99, overflow: 'hidden', marginTop: 14 }}>
                <div style={{
                    width: `${Math.max(5, safeProgress)}%`,
                    height: '100%',
                    background: 'linear-gradient(90deg, #366092, #5fc3ff)',
                    transition: 'width 300ms ease',
                }} />
            </div>
            <p style={{ margin: '10px 0 0', color: '#667', fontSize: 13 }}>
                {longRunningHint}
            </p>
        </div>
    )
}
