public inherited sharing class CaseRoutingHandler {
    public static void applyRoutingTier(List<Case> newRecords, Map<Id, Case> priorById) {
        for (Case currentCase : newRecords) {
            Case priorCase = priorById == null ? null : priorById.get(currentCase.Id);
            if (priorCase != null && currentCase.Priority == priorCase.Priority) {
                continue;
            }

            currentCase.Routing_Tier__c = currentCase.Priority == 'High'
                ? 'Tier2'
                : 'Tier1';
        }
    }
}
