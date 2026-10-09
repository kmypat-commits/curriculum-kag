import { useCallback, useRef, useState } from 'react'
import axios from 'axios'

export default function usePlanVariants() {
    const [variants, setVariants] = useState(null)
    const [activeVariant, setActiveVariant] = useState('A')
    const revision = useRef(0)

    const fetchVariants = useCallback(async (versionId, includeDescriptions = false, includeExplanations = false) => {
        const requestedRevision = ++revision.current
        const response = await axios.get(`/api/planner/${versionId}/variants`, {
            params: { include_descriptions: includeDescriptions, include_explanations: includeExplanations },
        })
        if (revision.current !== requestedRevision) return
        if (!response.data || response.data.length === 0) return
        const next = Object.fromEntries(response.data.map(item => [item.variant_type, item]))
        setVariants(next)
        setActiveVariant(current => {
            if (next[current]) return current
            const preferred = [...response.data].sort((a, b) =>
                (b.metrics?.min_lo_coverage || 0) - (a.metrics?.min_lo_coverage || 0) ||
                (b.metrics?.lo_coverage_percentage || 0) - (a.metrics?.lo_coverage_percentage || 0)
            )[0]
            return preferred?.variant_type || current
        })
    }, [])

    return { variants, setVariants, activeVariant, setActiveVariant, fetchVariants }
}
