pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: panel
    objectName: "countOutcomesPanel"
    required property var countingRounds
    required property var words
    required property string locale
    readonly property var editorState: countingRounds.state
    readonly property var selected: editorState.selected || ({})
    readonly property var selection: selected.selection || ({})
    readonly property var forms: editorState.f2_forms || ({})
    readonly property bool working: !!editorState.busy
    readonly property bool writer: editorState.role === "counting_officer"
    readonly property bool supervisor: editorState.role === "supervisor"
    readonly property bool editable: !!selected.id && writer && !working
        && !editorState.historical && !editorState.newer_revision
        && selected.status === "draft" && !!selected.f1_complete
        && !!selected.source_current && editorState.context.election
        && editorState.context.election.status === "active"
        && (!editorState.dirty_stage || editorState.dirty_stage === "f2")
    property var candidateRows: []
    property var reasonRows: []
    property var comparisonRows: []
    property string candidateKey: ""
    property string reasonKey: ""
    property string comparisonKey: ""
    property string pendingWorkflow: ""
    signal reveal(var control)
    Layout.fillWidth: true
    spacing: 20

    function t(key) { return words[key] || key }
    function exact(row, key) {
        var value = row[key + "_display"]
        if (value !== undefined) return value
        return row[key] === undefined || row[key] === null ? "—" : String(row[key])
    }
    function label(row) { return row["label_" + locale] || row.label_en || "" }
    function accepted(row) {
        return (editorState.accepted_inputs || []).find(function(item) {
            return item.candidate_id === row.candidate_id
        }) || ({})
    }
    function rejected(row) {
        return (editorState.rejected_inputs || []).find(function(item) {
            return item.reason_id === row.reason_id
        }) || ({})
    }
    function copyRows(rows) { return JSON.parse(JSON.stringify(rows)) }
    function syncRows() {
        var candidates = (editorState.accepted_inputs || []).map(function(row) {
            return {
                candidate_id: row.candidate_id,
                ballot_number: row.ballot_number,
                name: row.name
            }
        })
        var candidateJson = JSON.stringify(candidates)
        if (candidateJson !== candidateKey) {
            candidateKey = candidateJson
            candidateRows = candidates
        }
        var reasons = (editorState.rejected_inputs || []).map(function(row) {
            return {
                reason_id: row.reason_id,
                reason_revision: row.reason_revision,
                label_tc: row.label_tc,
                label_sc: row.label_sc,
                label_en: row.label_en,
                verified_source: row.verified_source,
                source_english: row.source_english,
                source_letter: row.source_letter,
                reference_page: row.reference_page,
                reference_printed_page: row.reference_printed_page,
                translation_provenance: row.translation_provenance,
                is_other: row.is_other,
                explanation_required: row.explanation_required,
                current_catalog: row.current_catalog
            }
        })
        var reasonJson = JSON.stringify(reasons)
        if (reasonJson !== reasonKey) {
            reasonKey = reasonJson
            reasonRows = reasons
        }
        var comparisons = editorState.selected.physical_comparisons || []
        var comparisonJson = JSON.stringify(comparisons)
        if (comparisonJson !== comparisonKey) {
            comparisonKey = comparisonJson
            comparisonRows = copyRows(comparisons)
        }
    }
    function workflowEnabled(action) {
        if (working || editorState.dirty || editorState.historical || editorState.newer_revision
                || !selected.id || !selected.source_current) return false
        if (action === "submit")
            return writer && selected.status === "draft" && !!selected.count_inputs_complete
        if (action === "approve")
            return supervisor && selected.status === "submitted"
                && !!selected.count_inputs_complete && !!selected.source_current
                && !(selected.approval_blockers || []).length
        if (action === "select")
            return supervisor && selected.status === "approved" && !!selected.approval_valid
        return false
    }
    function openWorkflow(action) {
        pendingWorkflow = action
        workflowDialog.open()
    }
    function runWorkflow(password) {
        if (pendingWorkflow === "approve") countingRounds.approveCount(password)
        else if (pendingWorkflow === "select") countingRounds.selectApproved(password)
    }
    function statusText(comparison) {
        return t("f2_comparison_" + comparison.status)
    }
    function moveFocus(field, forward) {
        var next = field.nextItemInFocusChain(forward)
        if (next) next.forceActiveFocus(forward ? Qt.TabFocusReason : Qt.BacktabFocusReason)
    }

    onLocaleChanged: syncRows()
    onWordsChanged: syncRows()
    Component.onCompleted: syncRows()
    Connections {
        target: panel.countingRounds
        function onStateChanged() {
            panel.syncRows()
            if (!panel.editorState.role) workflowPassword.clear()
        }
    }

    component Heading: Label {
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
        font.pixelSize: 20
        font.weight: Font.Medium
        color: "#25344b"
        Layout.fillWidth: true
    }
    component Entry: FormField {
        id: field
        readOnly: !panel.editable
        working: panel.working
        Layout.fillWidth: true
        onReveal: control => panel.reveal(control)
    }
    component Notes: TextArea {
        id: field
        required property string caption
        Layout.fillWidth: true
        implicitHeight: Math.max(92, contentHeight + topPadding + bottomPadding)
        textFormat: TextEdit.PlainText
        wrapMode: TextEdit.WordWrap
        clip: true
        selectByMouse: true
        readOnly: !panel.editable
        enabled: !panel.working
        leftPadding: 12
        rightPadding: 12
        topPadding: 12
        bottomPadding: 12
        topInset: 0
        Accessible.name: caption
        Keys.priority: Keys.BeforeItem
        Keys.onTabPressed: event => { panel.moveFocus(field, true); event.accepted = true }
        Keys.onBacktabPressed: event => { panel.moveFocus(field, false); event.accepted = true }
        onActiveFocusChanged: if (activeFocus) Qt.callLater(function() {
            if (field.activeFocus) panel.reveal(field)
        })
        background: Rectangle {
            radius: 8
            color: "white"
            border.color: field.activeFocus ? "#1967d2" : "#a7b2c2"
            border.width: field.activeFocus ? 2 : 1
        }
    }
    component Action: FormButton {
        id: button
        Layout.fillWidth: true
        implicitHeight: Math.max(48, buttonText.implicitHeight + 24)
        contentItem: Text {
            id: buttonText
            text: button.text
            textFormat: Text.PlainText
            font: button.font
            wrapMode: Text.WordWrap
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            color: button.enabled ? (button.highlighted ? "white" : "#1967d2") : "#8a96a8"
        }
        onReveal: control => panel.reveal(control)
    }

    visible: !!selected.id
    FormPanel {
        Layout.fillWidth: true
        implicitHeight: entry.implicitHeight + 40
        ColumnLayout {
            id: entry
            anchors.fill: parent
            anchors.margins: 20
            spacing: 14
            Heading { objectName: "countOutcomesTitle"; text: panel.t("f2_title") }
            FormCaption { text: panel.t("f2_hint") }
            FormCaption {
                visible: !panel.selected.f1_complete
                text: panel.t("f1_incomplete")
                color: "#8a5c16"
            }
            FormCaption {
                objectName: "f2RevisionStatus"
                text: panel.t("revision") + " " + panel.exact(panel.selected, "revision")
                    + " · " + panel.t(panel.selected.status || "draft")
            }
            FormCaption {
                visible: !!panel.editorState.historical
                text: panel.t("f2_historical")
            }
            FormCaption {
                visible: !!panel.selected.id && !panel.selected.source_current
                text: panel.t("count_round_basis_stale")
                color: "#8a5c16"
            }
            FormCaption { text: panel.t("f2_observation_time") }
            Entry {
                objectName: "f2EventAt"
                text: panel.forms.event_at || ""
                placeholderText: "YYYY-MM-DD HH:MM:SS.ffffff"
                Accessible.name: panel.t("f2_observation_time")
                onTextEdited: panel.countingRounds.setF2Field("event_at", text)
            }
            FormCaption { text: panel.t("f2_determination_start") }
            Entry {
                objectName: "f2DeterminationStartedAt"
                text: panel.forms.determination_started_at || ""
                placeholderText: "YYYY-MM-DD HH:MM:SS.ffffff"
                Accessible.name: panel.t("f2_determination_start")
                onTextEdited: panel.countingRounds.setF2Field("determination_started_at", text)
            }
            FormCaption { text: panel.t("f2_time_hint") }
            Heading { text: panel.t("f2_accepted_outcomes") }
            Repeater {
                model: panel.candidateRows
                ColumnLayout {
                    required property var modelData
                    Layout.fillWidth: true
                    spacing: 6
                    FormCaption {
                        text: modelData.ballot_number + " · " + modelData.name
                    }
                    FormCaption { text: panel.t("f2_accepted_quantity") }
                    Entry {
                        objectName: "f2AcceptedQuantity_" + modelData.candidate_id
                        text: panel.accepted(modelData).quantity || ""
                        Accessible.name: modelData.name + " · " + panel.t("f2_accepted_quantity")
                        onTextEdited: panel.countingRounds.setAcceptedQuantity(
                            modelData.candidate_id, text)
                    }
                }
            }
            Heading { text: panel.t("f2_rejected_outcomes") }
            FormCaption { text: panel.t("f2_reason_source_note") }
            Repeater {
                model: panel.reasonRows
                ColumnLayout {
                    id: reasonRow
                    required property var modelData
                    Layout.fillWidth: true
                    spacing: 8
                    FormCaption {
                        objectName: "f2ReasonLabel_" + reasonRow.modelData.reason_id
                        text: panel.label(reasonRow.modelData)
                    }
                    FormCaption {
                        objectName: "f2SourceEnglish_" + reasonRow.modelData.reason_id
                        visible: !!reasonRow.modelData.source_english
                        text: panel.t("f2_source_english") + ": "
                            + (reasonRow.modelData.source_english || "")
                        wrapMode: Text.WordWrap
                    }
                    FormCaption {
                        visible: !!reasonRow.modelData.verified_source
                        text: panel.t("f2_source_letter") + ": "
                            + (reasonRow.modelData.source_letter || "—")
                            + " · " + panel.t("f2_reference_pages") + " "
                            + (reasonRow.modelData.reference_page || "—") + " / "
                            + (reasonRow.modelData.reference_printed_page || "—")
                    }
                    FormCaption {
                        visible: !!reasonRow.modelData.verified_source
                        text: panel.t("f2_translation_provenance") + ": "
                            + panel.t("f2_project_translation")
                    }
                    FormCaption {
                        visible: !reasonRow.modelData.verified_source
                        text: panel.t("f2_project_reason")
                    }
                    FormCaption { text: panel.t("f2_rejected_quantity") }
                    Entry {
                        objectName: "f2RejectedQuantity_" + reasonRow.modelData.reason_id
                        text: panel.rejected(reasonRow.modelData).quantity || ""
                        Accessible.name: panel.label(reasonRow.modelData) + " · "
                            + panel.t("f2_rejected_quantity")
                        onTextEdited: panel.countingRounds.setRejectedQuantity(
                            reasonRow.modelData.reason_id, text)
                    }
                    FormCaption {
                        visible: !!reasonRow.modelData.explanation_required
                        text: panel.t("f2_explanation_required")
                    }
                    Notes {
                        objectName: "f2RejectedExplanation_" + reasonRow.modelData.reason_id
                        visible: !!reasonRow.modelData.explanation_required
                            || !!panel.rejected(reasonRow.modelData).explanation
                        caption: panel.t("f2_explanation")
                        text: panel.rejected(reasonRow.modelData).explanation || ""
                        onTextChanged: if (activeFocus)
                            panel.countingRounds.setRejectedExplanation(
                                reasonRow.modelData.reason_id, text)
                    }
                    FormCaption {
                        visible: !reasonRow.modelData.current_catalog
                        text: panel.t("f1_retired_reason")
                        color: "#8a5c16"
                    }
                }
            }
            FormCaption { text: panel.t("f2_notes") }
            Notes {
                objectName: "f2Notes"
                caption: panel.t("f2_notes")
                text: panel.forms.notes || ""
                onTextChanged: if (activeFocus)
                    panel.countingRounds.setF2Field("notes", text)
            }
            FormCaption { text: panel.t("f2_amendment_reason") }
            Notes {
                objectName: "f2AmendmentReason"
                caption: panel.t("f2_amendment_reason")
                text: panel.forms.amendment_reason || ""
                onTextChanged: if (activeFocus)
                    panel.countingRounds.setF2Field("amendment_reason", text)
            }
            Repeater {
                model: panel.selected.blockers || []
                FormCaption {
                    required property var modelData
                    text: panel.t(modelData.code)
                    color: "#8a5c16"
                    wrapMode: Text.WordWrap
                }
            }
            Action {
                objectName: "f2Save"
                visible: panel.writer && !!panel.selected.id && !!panel.selected.f1_complete
                    && panel.selected.status === "draft"
                text: panel.t("f2_save")
                highlighted: true
                working: panel.working
                enabled: panel.editable && !!panel.editorState.dirty
                    && panel.editorState.dirty_stage === "f2"
                onClicked: panel.countingRounds.saveF2()
            }
        }
    }

    FormPanel {
        visible: !!panel.selected.f2
        Layout.fillWidth: true
        implicitHeight: results.implicitHeight + 40
        ColumnLayout {
            id: results
            anchors.fill: parent
            anchors.margins: 20
            spacing: 14
            Heading { text: panel.t("f2_results_title") }
            FormCaption {
                objectName: "countInputCompleteness"
                text: panel.t(panel.selected.count_inputs_complete
                    ? "f2_inputs_complete" : "f2_inputs_incomplete")
            }
            FormCaption {
                objectName: "countWorkflowCompletion"
                text: panel.t(panel.selected.count_complete
                    ? "f2_workflow_complete" : "f2_workflow_incomplete")
            }
            FormCaption {
                objectName: "countWorkflowStatus"
                text: panel.t("f2_workflow_status") + ": "
                    + panel.t(panel.selected.status || "draft")
            }
            GridLayout {
                Layout.fillWidth: true
                columns: panel.width > 700 ? 2 : 1
                columnSpacing: 20
                rowSpacing: 16
                Repeater {
                    model: [
                        "accepted_questionable_quantity",
                        "rejected_questionable_quantity",
                        "final_valid_quantity",
                        "final_invalid_quantity",
                        "final_accounted_quantity",
                        "actual_counted_quantity"
                    ]
                    ColumnLayout {
                        required property string modelData
                        Layout.fillWidth: true
                        FormCaption { text: panel.t("f2_" + modelData) }
                        Label {
                            objectName: "countTotal_" + modelData
                            text: panel.exact(panel.selected, modelData)
                            textFormat: Text.PlainText
                            wrapMode: Text.WrapAnywhere
                            color: "#25344b"
                            Layout.fillWidth: true
                        }
                    }
                }
            }
            Heading { text: panel.t("f2_final_candidates") }
            Repeater {
                model: panel.selected.final_candidate_votes || []
                RowLayout {
                    required property var modelData
                    Layout.fillWidth: true
                    FormCaption {
                        text: modelData.ballot_number + " · " + modelData.name
                        Layout.fillWidth: true
                    }
                    FormCaption {
                        objectName: "countFinalCandidateQuantity_" + modelData.candidate_id
                        text: panel.exact(modelData, "quantity")
                    }
                }
            }
            Heading { text: panel.t("f2_physical_comparisons") }
            Repeater {
                model: panel.comparisonRows
                ColumnLayout {
                    required property var modelData
                    Layout.fillWidth: true
                    spacing: 6
                    FormCaption {
                        text: panel.t("f2_source_" + modelData.source) + " · "
                            + panel.statusText(modelData)
                    }
                    FormCaption {
                        objectName: "countComparison_" + modelData.source
                        text: panel.t("f2_expected") + " "
                            + panel.exact(modelData, "expected_quantity") + " · "
                            + panel.t("f2_actual") + " "
                            + panel.exact(modelData, "actual_quantity") + " · "
                            + panel.t("f2_difference") + " "
                            + panel.exact(modelData, "difference_quantity")
                        wrapMode: Text.WordWrap
                    }
                }
            }
            Heading { text: panel.t("f2_approval_blockers") }
            Repeater {
                model: panel.selected.approval_blockers || []
                FormCaption {
                    required property var modelData
                    text: panel.t(modelData.code)
                        + (modelData.source ? " · " + panel.t("f2_source_" + modelData.source) : "")
                        + (modelData.difference_quantity_display
                            ? " · " + modelData.difference_quantity_display : "")
                    color: "#8a5c16"
                    wrapMode: Text.WordWrap
                }
            }
            FormCaption {
                objectName: "countSubmittedAt"
                visible: !!panel.selected.submitted_at
                text: panel.t("f2_submitted_at") + " · "
                    + panel.countingRounds.formatTime(panel.selected.submitted_at)
            }
            FormCaption {
                objectName: "countSubmittedBy"
                visible: panel.selected.submitted_by !== undefined
                text: panel.t("f2_submitted_by") + " · " + String(panel.selected.submitted_by)
            }
            FormCaption {
                objectName: "countApprovedAt"
                visible: !!panel.selected.approved_at
                text: panel.t("f2_approved_at") + " · "
                    + panel.countingRounds.formatTime(panel.selected.approved_at)
            }
            FormCaption {
                objectName: "countApprovedBy"
                visible: panel.selected.approved_by !== undefined
                text: panel.t("f2_approved_by") + " · " + String(panel.selected.approved_by)
            }
            FormCaption {
                objectName: "countApprovalValidity"
                visible: panel.selected.status === "approved"
                text: panel.t(panel.selected.approval_valid
                    ? "f2_approval_valid" : "f2_approval_invalid")
            }
            FormCaption {
                objectName: "countSelectionState"
                visible: !!panel.selection.revision
                text: panel.t(panel.selection.valid
                    ? "f2_selected" : "f2_selection_historical")
                    + " · " + panel.t("revision") + " "
                    + panel.exact(panel.selection, "revision")
            }
            FormCaption {
                objectName: "countSelectedAt"
                visible: !!panel.selection.selected_at
                text: panel.t("f2_selected_at") + " · "
                    + panel.countingRounds.formatTime(panel.selection.selected_at)
            }
            FormCaption {
                objectName: "countSelectedBy"
                visible: panel.selection.actor_id !== undefined
                text: panel.t("f2_selected_by") + " · " + String(panel.selection.actor_id)
            }
            GridLayout {
                Layout.fillWidth: true
                columns: panel.width > 700 ? 3 : 1
                columnSpacing: 12
                rowSpacing: 12
                Action {
                    objectName: "countSubmit"
                    visible: panel.writer && panel.selected.status === "draft"
                    text: panel.t("f2_submit")
                    working: panel.working
                    enabled: panel.workflowEnabled("submit")
                    onClicked: panel.countingRounds.submitCount()
                }
                Action {
                    objectName: "countApprove"
                    visible: panel.supervisor && panel.selected.status === "submitted"
                    text: panel.t("f2_approve")
                    working: panel.working
                    enabled: panel.workflowEnabled("approve")
                    onClicked: panel.openWorkflow("approve")
                }
                Action {
                    objectName: "countSelect"
                    visible: panel.supervisor && panel.selected.status === "approved"
                    text: panel.t("f2_select")
                    working: panel.working
                    enabled: panel.workflowEnabled("select")
                    onClicked: panel.openWorkflow("select")
                }
            }
        }
    }

    Dialog {
        id: workflowDialog
        objectName: "countWorkflowPasswordDialog"
        modal: true
        focus: true
        anchors.centerIn: Overlay.overlay
        width: Math.min(460, Overlay.overlay.width - 40)
        title: panel.t(pendingWorkflow === "approve" ? "f2_approve_dialog" : "f2_select_dialog")
        onOpened: workflowPassword.forceActiveFocus()
        onRejected: workflowPassword.clear()
        onAccepted: {
            var password = workflowPassword.text
            workflowPassword.clear()
            panel.runWorkflow(password)
        }
        onClosed: {
            workflowPassword.clear()
            panel.pendingWorkflow = ""
        }
        contentItem: ColumnLayout {
            spacing: 12
            FormCaption {
                text: panel.t("f2_dialog_revision") + " " + panel.exact(panel.selected, "revision")
            }
            FormField {
                id: workflowPassword
                objectName: "countWorkflowPassword"
                echoMode: TextInput.Password
                maximumLength: 128
                Accessible.name: panel.t("password")
                onReveal: control => panel.reveal(control)
            }
        }
        footer: DialogButtonBox {
            Button {
                objectName: "countWorkflowCancel"
                text: panel.t("cancel")
                DialogButtonBox.buttonRole: DialogButtonBox.RejectRole
            }
            Button {
                objectName: "countWorkflowConfirm"
                text: panel.t("confirm")
                enabled: workflowPassword.text.length > 0
                DialogButtonBox.buttonRole: DialogButtonBox.AcceptRole
            }
        }
    }
}
