@IsTest
private class CaseRoutingHandlerTest {
    private static Case buildCase(String subjectValue, String priorityValue) {
        return new Case(
            Subject = subjectValue,
            Status = 'New',
            Origin = 'Phone',
            Priority = priorityValue
        );
    }

    private static User createSupportUser() {
        Profile supportProfile = [
            SELECT Id
            FROM Profile
            WHERE Name = 'Custom: Support Profile'
            LIMIT 1
        ];
        User supportUser = new User(
            Alias = 'croute',
            Email = 'case-routing-test@example.com',
            EmailEncodingKey = 'UTF-8',
            LastName = 'Routing Test',
            LanguageLocaleKey = 'en_US',
            LocaleSidKey = 'en_US',
            ProfileId = supportProfile.Id,
            TimeZoneSidKey = 'America/Los_Angeles',
            Username = 'case-routing-test-' + String.valueOf(DateTime.now().getTime()) + '@example.com'
        );
        insert supportUser;
        return supportUser;
    }

    @IsTest
    static void routesHighAndOtherPrioritiesOnInsert() {
        User supportUser = createSupportUser();
        System.runAs(supportUser) {
            List<Case> cases = new List<Case>{
                buildCase('High priority', 'High'),
                buildCase('Medium priority', 'Medium'),
                buildCase('Low priority', 'Low'),
                buildCase('No priority', null)
            };

            insert cases;

            Set<Id> caseIds = new Set<Id>();
            for (Case insertedCase : cases) {
                caseIds.add(insertedCase.Id);
            }
            Map<Id, Case> actualById = new Map<Id, Case>([
                SELECT Id, Routing_Tier__c
                FROM Case
                WHERE Id IN :caseIds
            ]);

            System.assertEquals(4, actualById.size(), 'All inserted Cases should be returned');
            System.assertEquals('Tier2', actualById.get(cases[0].Id).Routing_Tier__c);
            System.assertEquals('Tier1', actualById.get(cases[1].Id).Routing_Tier__c);
            System.assertEquals('Tier1', actualById.get(cases[2].Id).Routing_Tier__c);
            System.assertEquals('Tier1', actualById.get(cases[3].Id).Routing_Tier__c);
        }
    }

    @IsTest
    static void recalculatesWhenPriorityChanges() {
        User supportUser = createSupportUser();
        System.runAs(supportUser) {
            List<Case> cases = new List<Case>{
                buildCase('Change to Low', 'High'),
                buildCase('Change to High', 'Medium')
            };
            insert cases;

            cases[0].Priority = 'Low';
            cases[1].Priority = 'High';
            update cases;

            Set<Id> caseIds = new Set<Id>();
            for (Case changedCase : cases) {
                caseIds.add(changedCase.Id);
            }
            Map<Id, Case> actualById = new Map<Id, Case>([
                SELECT Id, Routing_Tier__c
                FROM Case
                WHERE Id IN :caseIds
            ]);

            System.assertEquals('Tier1', actualById.get(cases[0].Id).Routing_Tier__c);
            System.assertEquals('Tier2', actualById.get(cases[1].Id).Routing_Tier__c);
        }
    }

    @IsTest
    static void routesTwoHundredCasesInOneTransaction() {
        User supportUser = createSupportUser();
        System.runAs(supportUser) {
            List<Case> cases = new List<Case>();
            Boolean useHighPriority = true;
            for (Integer indexValue = 0; indexValue < 200; indexValue++) {
                String priorityValue = useHighPriority ? 'High' : 'Low';
                cases.add(buildCase('Bulk routing ' + String.valueOf(indexValue), priorityValue));
                useHighPriority = !useHighPriority;
            }

            insert cases;

            Set<Id> caseIds = new Set<Id>();
            for (Case insertedCase : cases) {
                caseIds.add(insertedCase.Id);
            }
            Map<Id, Case> actualById = new Map<Id, Case>([
                SELECT Id, Priority, Routing_Tier__c
                FROM Case
                WHERE Id IN :caseIds
            ]);

            System.assertEquals(200, actualById.size(), 'All 200 Cases should be inserted');
            for (Case insertedCase : cases) {
                String expectedTier = insertedCase.Priority == 'High' ? 'Tier2' : 'Tier1';
                System.assertEquals(expectedTier, actualById.get(insertedCase.Id).Routing_Tier__c);
            }
        }
    }
}
