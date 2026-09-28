export async function saveCurriculumRequirements(patch, projectId, constraints, requirements) {
    const { curriculum_confirmations: _serverIssued, ...editableConstraints } = constraints || {}
    const response = await patch(`/api/projects/${projectId}/constraints`, {
        constraints: {
            ...editableConstraints,
            curriculum_requirements: requirements,
        },
    })
    return response.data.constraints
}

export async function loadCoreEvidencePreview(get, projectId, versionId, blockId, courseId) {
    const response = await get(`/api/projects/${projectId}/curriculum-confirmations/preview`, {
        params: { project_version_id: versionId, block_id: blockId, course_id: courseId },
    })
    return response.data
}

export async function confirmCoreMatch(post, projectId, versionId, reviewed) {
    const response = await post(`/api/projects/${projectId}/curriculum-confirmations`, {
        project_version_id: versionId, ...reviewed,
    })
    return response.data.confirmation
}
