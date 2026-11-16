@IsTest
private inherited sharing class CaseRoutingTierHandlerTest {
    @IsTest
    static void picklistHasTierValues() {
        Set<String> values = new Set<String>();
        for (Schema.PicklistEntry option : Case.Routing_Tier__c.getDescribe().getPicklistValues()) {
            values.add(option.getValue());
        }

        System.assertEquals(new Set<String>{'Tier1', 'Tier2'}, values);
    }

    @IsTest
    static void routesNewCasesByPriority() {
        List<Case> casesToInsert = new List<Case>{
            buildCase('High'),
            buildCase('Low'),
            buildCase('Medium'),
            buildCase(null)
        };
        insert casesToInsert;

        Map<Id, Case> actualCases = loadCases(casesToInsert);
        System.assertEquals('Tier2', actualCases.get(casesToInsert[0].Id).Routing_Tier__c);
        System.assertEquals('Tier1', actualCases.get(casesToInsert[1].Id).Routing_Tier__c);
        System.assertEquals('Tier1', actualCases.get(casesToInsert[2].Id).Routing_Tier__c);
        System.assertEquals('Tier1', actualCases.get(casesToInsert[3].Id).Routing_Tier__c);
    }

    @IsTest
    static void recalculatesWhenPriorityChanges() {
        Case caseRecord = buildCase('Low');
        insert caseRecord;

        caseRecord.Priority = 'High';
        update caseRecord;
        Case actualCase = [
            SELECT Id, Priority, Routing_Tier__c
            FROM Case
            WHERE Id = :caseRecord.Id
        ];
        System.assertEquals('Tier2', actualCase.Routing_Tier__c);

        actualCase.Priority = 'Low';
        update actualCase;
        actualCase = [
            SELECT Id, Priority, Routing_Tier__c
            FROM Case
            WHERE Id = :caseRecord.Id
        ];
        System.assertEquals('Tier1', actualCase.Routing_Tier__c);
    }

    @IsTest
    static void doesNotRecalculateWhenPriorityIsUnchanged() {
        Case caseRecord = buildCase('Low');
        insert caseRecord;

        caseRecord.Routing_Tier__c = 'Tier2';
        update caseRecord;

        Case actualCase = [
            SELECT Id, Routing_Tier__c
            FROM Case
            WHERE Id = :caseRecord.Id
        ];
        System.assertEquals('Tier2', actualCase.Routing_Tier__c);
    }

    @IsTest
    static void routesTwoHundredCases() {
        List<Case> casesToInsert = new List<Case>();
        Boolean highPriority = true;
        for (Integer indexValue = 0; indexValue < 200; indexValue++) {
            casesToInsert.add(buildCase(highPriority ? 'High' : 'Low'));
            highPriority = !highPriority;
        }
        insert casesToInsert;

        Map<Id, Case> actualCases = loadCases(casesToInsert);
        System.assertEquals(200, actualCases.size());
        for (Case insertedCase : casesToInsert) {
            String expectedTier = insertedCase.Priority == 'High' ? 'Tier2' : 'Tier1';
            System.assertEquals(expectedTier, actualCases.get(insertedCase.Id).Routing_Tier__c);
        }
    }

    private static Case buildCase(String priorityValue) {
        return new Case(
            Subject = 'Routing tier test',
            Status = 'New',
            Origin = 'Phone',
            Priority = priorityValue
        );
    }

    private static Map<Id, Case> loadCases(List<Case> casesToLoad) {
        Set<Id> caseIds = new Set<Id>();
        for (Case caseRecord : casesToLoad) {
            caseIds.add(caseRecord.Id);
        }

        return new Map<Id, Case>([
            SELECT Id, Priority, Routing_Tier__c
            FROM Case
            WHERE Id IN :caseIds
        ]);
    }
}
