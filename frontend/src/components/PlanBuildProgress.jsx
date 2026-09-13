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
    const timedOut = status?.state === 'timed_out'
    if (!active && !timedOut) return null

    const safeProgress = Math.max(0, Math.min(100, Number(progress) || 0))
    return (
        <div className={`card build-progress-card${timedOut ? ' build-progress-card--timeout' : ''}`} role={timedOut ? 'alert' : 'status'} aria-live="polite">
            <div className="build-progress-header">
                <div className="build-progress-copy">
                    <h3>{title}</h3>
                    <div className="build-progress-stage">{stageLabel(status.stage)}</div>
                    {stageDetail && <div className="build-progress-detail">{stageDetail}</div>}
                    {elapsedLabel && <div className="build-progress-detail">{elapsedLabel}</div>}
                </div>
                <strong className="build-progress-value">
                    {timedOut ? stageLabel(status.stage) : (stageDetail || `${safeProgress}%`)}
                </strong>
            </div>
            {!timedOut && <div className="build-progress-meter" role="progressbar" aria-label={title} aria-valuemin="0" aria-valuemax="100" aria-valuenow={safeProgress}>
                <div className="build-progress-meter-fill" style={{ width: `${Math.max(5, safeProgress)}%` }} />
            </div>}
            <p className="build-progress-hint">
                {longRunningHint}
            </p>
        </div>
    )
}
