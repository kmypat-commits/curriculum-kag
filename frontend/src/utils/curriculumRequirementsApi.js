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
