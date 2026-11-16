public inherited sharing class CaseRoutingTierHandler {
    public static void apply(List<Case> newCases, Map<Id, Case> oldMap) {
        if (newCases == null || newCases.isEmpty()) {
            return;
        }

        for (Case currentCase : newCases) {
            Boolean isInsert = oldMap == null;
            Boolean priorityChanged = !isInsert
                && currentCase.Priority != oldMap.get(currentCase.Id).Priority;

            if (isInsert || priorityChanged) {
                currentCase.Routing_Tier__c = currentCase.Priority == 'High'
                    ? 'Tier2'
                    : 'Tier1';
            }
        }
    }
}
