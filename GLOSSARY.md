# Election Management and Voting System

Terms for the staff application that administers physical-ballot polling and records counting results.

## Language

**Election**:
A coordinated electoral event containing voting and counting for separate constituencies. Its constituencies have their own candidate lists and results.

**Active election**:
The election currently authorized to conduct polling and counting. It remains active until its counts and required recounts are finalized, and only one election may be active at a time.

**Constituency (選區)**:
An electoral area with its own candidates and results within an election. Each constituency in this prototype elects one candidate, with one choice per valid ballot.
_Avoid_: Polling station, election

**Candidate (候選人)**:
A person standing for election in a constituency and appearing in that constituency's candidate list and vote totals.

**Ballot (選票)**:
A physical paper ballot issued for an elector to record a voting choice.
_Avoid_: Electronic vote

**Ballot issuance (發票)**:
The act of providing a physical ballot to an elector for voting.
_Avoid_: Invoicing, invoice issuance

**Ballot allocation (派發選票至發票櫃台)**:
The transfer of ballot stock to an issuance counter for later issuance to electors.
_Avoid_: Ballot issuance to electors

**Polling station (投票站)**:
A physical location where electors attend to cast their ballots, assigned to one constituency for the election.

**Counting station (點票站)**:
A location that counts its own ballot boxes, boxes received from other polling stations in the same constituency, or both.

**Ballot-box transfer**:
The recorded handover of a sealed box from its polling station to its designated counting station.

**Counting scope**:
The identified set of received ballot boxes covered by a tally at a counting station.

**Issuance counter (發票櫃台)**:
A staffed desk within a polling station where ballot papers are provided to electors.
_Avoid_: Invoice counter

**Tendered ballot (重複選票)**:
A ballot issued when an earlier ballot issuance is recorded for an elector's identity and the presiding officer is uncertain whether that elector received the earlier ballot. It is accounted for separately and excluded from candidate vote totals.
_Avoid_: Replacement ballot, ordinary duplicate vote

**Spoilt original (損壞選票)**:
A ballot damaged or incorrectly marked before being cast, surrendered and cancelled when a replacement is issued.
_Avoid_: Rejected ballot found during counting

**Replacement ballot**:
A new ballot provided in exchange for a surrendered spoilt original. It substitutes for the original rather than representing another ordinary voter.

**Retrieved-unused ballot (未用選票)**:
A previously issued ballot retrieved because it was refused, found in the station, or held pending the elector's return.
_Avoid_: Never-issued stock

**Unissued stock**:
Ballot papers that have not been issued to electors, including papers still held centrally, at desks, or in unused reserves.
_Avoid_: Retrieved-unused ballots

**Questionable ballot (問題選票)**:
A cast ballot whose validity requires determination before it can be allocated to a candidate's accepted total or a rejection reason.

**Count (點票)**:
The tallying of physical ballots to determine voting totals and results.

**Recount (重新點票)**:
A subsequent tally of ballots that have already been counted.

**Constituency-wide recount instruction**:
A Supervisor's instruction to recount all required counting scopes of one constituency, with its original scope membership, reason and time. Its completion history remains available as later counts and instructions progress.

**Count round**:
One tally attempt for a counting scope. A recount creates a subsequent round while preserving the earlier tally.

**Selected approved round**:
The reviewed tally explicitly chosen to contribute to the current result for a counting scope.

**Physical discrepancy**:
A recorded difference between an expected physical quantity and the quantity actually observed. It remains visible with its explanation and review outcome.

**EPR fallback mode**:
The polling procedure used when the external electronic poll register is unavailable but the management application remains available. Staff supply the ballot and turnout information needed to continue operational reporting.

**Polling Officer**:
A staff member responsible for recording ballot issuance and other polling-station operations.

**Counting Officer**:
A staff member responsible for recording counts and recounts of physical ballots.

**Supervisor**:
A staff member responsible for reviewing operational records and approving completion.
