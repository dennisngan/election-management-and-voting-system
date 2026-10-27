pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Dialogs
import QtQuick.Layouts
import QtCore

ColumnLayout {
    id: page
    objectName: "constituencyResultsPage"
    required property var results
    required property var words
    property string locale: "tc"
    property string pendingFormat: "pdf"
    property string pendingLocale: "tc"
    property int observedAccountId: 0
    readonly property var editorState: results.state
    readonly property var result: editorState.result || ({})
    readonly property var resultContext: result.context || ({})
    readonly property var election: resultContext.election || ({})
    readonly property var constituency: resultContext.constituency || ({})
    readonly property var candidateTotals: result.candidate_totals || []
    readonly property var tieRows: page.tieCandidateRows()
    readonly property bool working: !!editorState.busy
    readonly property bool loading: page.working || !!editorState.refreshing
    readonly property bool uncertain: !!editorState.uncertain_save
    readonly property bool stale: !!editorState.newer_basis
    readonly property bool supervisor: editorState.role === "supervisor"
    readonly property bool completeTie: result.complete === true
        && election.status === "active" && (result.tie_candidate_ids || []).length > 1
    readonly property bool canEdit: supervisor && completeTie && !working && !stale && !uncertain
    readonly property bool reportBlocked: working || !!editorState.dirty || stale || uncertain
        || !!editorState.recount_protected
    signal reveal(var control)
    spacing: 20

    function t(key) { return words[key] || words.constituency_results_not_recorded || "—" }
    function exact(row, key) {
        var shown = row[key + "_display"]
        if (shown !== undefined) return shown
        var value = row[key]
        return value === undefined || value === null ? "—" : String(value)
    }
    function candidate(candidateId) {
        for (var index = 0; index < candidateTotals.length; index++)
            if (candidateTotals[index].candidate_id === candidateId) return candidateTotals[index]
        return ({candidate_id: candidateId, name: t("constituency_results_not_recorded")})
    }
    function candidateName(candidateId) {
        var row = candidate(candidateId)
        return (row.name || t("constituency_results_not_recorded"))
            + " · " + t("constituency_results_candidate_id") + " " + candidateId
    }
    function tieCandidateRows() {
        return (result.tie_candidate_ids || []).map(function(candidateId) {
            var row = candidate(candidateId)
            return {
                candidate_id: candidateId,
                label: row.ballot_number + " · " + row.name
            }
        })
    }
    function selectedCandidateIndex() {
        for (var index = 0; index < tieRows.length; index++)
            if (tieRows[index].candidate_id === editorState.selected_candidate_id) return index
        return -1
    }
    function candidateList(ids) {
        return (ids || []).map(function(id) { return page.candidateName(id) }).join(" · ")
            || t("constituency_results_none")
    }
    function stationLabel(station) {
        if (!station) return t("constituency_results_not_recorded")
        var code = station.code || ""
        var name = station.name || ""
        return "#" + (station.id || "?") + " · " + code + (name ? " · " + name : "")
    }
    function pendingLabel(row) {
        var parts = [t("constituency_results_pending_" + row.code)]
        if (row.station_id !== undefined) parts.push(t("constituency_results_station") + " #" + row.station_id)
        if (row.scope_id !== undefined) parts.push(t("constituency_results_scope") + " #" + row.scope_id)
        if (row.scope_revision !== undefined)
            parts.push(t("constituency_results_scope_revision") + " " + row.scope_revision)
        if (row.source_accounting_revisions && row.source_accounting_revisions.length)
            parts.push(row.source_accounting_revisions.map(function(source) {
                return t("constituency_results_station") + " #" + source.station_id
                    + " · P(18) #" + source.record_id + " · "
                    + t("constituency_results_accounting_revision") + " " + source.revision
                    + " · " + (words[source.status] || source.status)
                    + " · " + t("constituency_results_source_current") + ": "
                    + t(source.source_current ? "constituency_results_yes" : "constituency_results_no")
                    + " · " + t("constituency_results_approval_valid") + ": "
                    + t(source.approval_valid ? "constituency_results_yes" : "constituency_results_no")
            }).join("; "))
        if (row.box_ids && row.box_ids.length)
            parts.push(t("constituency_results_boxes") + " " + row.box_ids.join(", "))
        if (row.blockers && row.blockers.length)
            parts.push(row.blockers.map(function(item) {
                return words["counting_scope_blocker_" + item.code]
                    || t("constituency_results_pending_reason")
            }).join(" · "))
        return parts.join(" · ")
    }
    function sourceStatus(value) {
        if (value === "received") return words.box_received_status || t("constituency_results_not_recorded")
        if (value === "departed") return words.box_departed_status || t("constituency_results_not_recorded")
        if (value === "prepared") return t("constituency_results_box_prepared_status")
        return words[value] || t("constituency_results_not_recorded")
    }
    function exportReport(format) {
        if (!result.basis_digest || reportBlocked) return
        pendingFormat = format
        pendingLocale = locale
        exportDialog.nameFilters = format === "pdf" ? ["PDF (*.pdf)"] : ["CSV (*.csv)"]
        exportDialog.defaultSuffix = format
        exportDialog.selectedFile = Qt.resolvedUrl(exportDialog.currentFolder.toString()
            + "/constituency-" + constituency.id + "-results-" + locale + "." + format)
        exportDialog.open()
    }
    function moveFocus(control, forward) {
        var next = control.nextItemInFocusChain(forward)
        if (next) next.forceActiveFocus(forward ? Qt.TabFocusReason : Qt.BacktabFocusReason)
    }

    component Heading: Label {
        textFormat: Text.PlainText
        color: "#25344b"
        font.pixelSize: 20
        font.weight: Font.Medium
        wrapMode: Text.WordWrap
        Layout.fillWidth: true
    }
    component Action: FormButton {
        id: action
        Layout.fillWidth: true
        implicitHeight: Math.max(48, actionText.implicitHeight + 24)
        contentItem: Text {
            id: actionText
            text: action.text
            textFormat: Text.PlainText
            font: action.font
            wrapMode: Text.WordWrap
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            color: action.enabled ? (action.highlighted ? "white" : "#1967d2") : "#8a96a8"
        }
        onReveal: control => page.reveal(control)
    }
    component Detail: ColumnLayout {
        id: detail
        required property string caption
        required property string value
        property string valueObjectName: ""
        Layout.fillWidth: true
        spacing: 4
        FormCaption { text: detail.caption }
        Label {
            objectName: detail.valueObjectName
            text: detail.value
            textFormat: Text.PlainText
            color: "#25344b"
            wrapMode: Text.WrapAnywhere
            Layout.fillWidth: true
        }
    }

    RowLayout {
        Layout.fillWidth: true
        Heading {
            objectName: "constituencyResultsTitle"
            text: page.t("constituency_results_title")
            font.pixelSize: 28
        }
        BusyIndicator {
            running: page.loading
            visible: running
            implicitWidth: 28
            implicitHeight: 28
            Accessible.name: page.t("constituency_results_loading")
        }
        FormButton {
            objectName: "constituencyResultsRefresh"
            text: page.t("constituency_results_refresh")
            flat: true
            highlighted: false
            working: page.loading
            enabled: !page.loading
            onClicked: page.results.reload()
            onReveal: control => page.reveal(control)
        }
    }
    Label {
        Layout.fillWidth: true
        text: page.t("constituency_results_intro")
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
        color: "#52647d"
    }
    FormNotice {
        objectName: "constituencyResultsNotice"
        words: page.words
        error: page.editorState.error
        notice: page.editorState.notice
        onReveal: control => page.reveal(control)
    }
    FormNotice {
        objectName: "constituencyResultsNewerBasisNotice"
        words: page.words
        autoReveal: false
        error: page.stale ? "constituency_result_newer_basis" : ""
        onReveal: control => page.reveal(control)
    }
    FormCaption {
        visible: !page.editorState.constituency_id
        text: page.t("constituency_results_select_station")
    }
    FormCaption {
        visible: !!page.editorState.constituency_id && page.supervisor && !page.result.basis_digest
            && !page.working
        text: page.t("constituency_results_loading")
    }
    FormCaption {
        visible: !!page.result.basis_digest && !page.supervisor
        text: page.t("constituency_results_read_only")
    }

    FormPanel {
        objectName: "constituencyResultsStatusPanel"
        visible: !!page.result.basis_digest
        implicitHeight: statusColumn.implicitHeight + 40
        ColumnLayout {
            id: statusColumn
            anchors.fill: parent
            anchors.margins: 20
            spacing: 12
            Heading { text: page.t("constituency_results_context") }
            GridLayout {
                Layout.fillWidth: true
                columns: page.width > 760 ? 2 : 1
                columnSpacing: 18
                rowSpacing: 12
                Detail {
                    caption: page.t("selected_election")
                    value: (page.election.name || "") + " · "
                        + page.t(page.election.status || "constituency_results_not_recorded")
                }
                Detail {
                    caption: page.t("constituency_name")
                    value: (page.constituency.code || "") + " · " + (page.constituency.name || "")
                }
                Detail {
                    valueObjectName: "constituencyResultsCompleteValue"
                    caption: page.t("constituency_results_complete")
                    value: page.result.complete ? page.t("constituency_results_yes")
                        : page.t("constituency_results_no")
                }
                Detail {
                    valueObjectName: "constituencyResultsProvisionalValue"
                    caption: page.t("constituency_results_provisional")
                    value: page.result.provisional ? page.t("constituency_results_yes")
                        : page.t("constituency_results_no")
                }
                Detail {
                    caption: page.t("constituency_results_leaders")
                    value: page.candidateList(page.result.leader_candidate_ids)
                }
                Detail {
                    visible: (page.result.tie_candidate_ids || []).length > 1
                        && !page.result.resolved_candidate_id
                    caption: page.t("constituency_results_unresolved_tie")
                    value: page.candidateList(page.result.tie_candidate_ids)
                }
                Detail {
                    visible: !!page.result.resolved_candidate_id
                    caption: page.t("constituency_results_resolved_candidate")
                    value: page.candidateName(page.result.resolved_candidate_id)
                }
            }
        }
    }

    FormPanel {
        objectName: "constituencyResultsCandidatesPanel"
        visible: !!page.result.basis_digest
        implicitHeight: candidatesColumn.implicitHeight + 40
        ColumnLayout {
            id: candidatesColumn
            anchors.fill: parent
            anchors.margins: 20
            spacing: 12
            Heading { text: page.t("constituency_results_candidate_totals") }
            Repeater {
                model: page.candidateTotals
                delegate: FormPanel {
                    required property var modelData
                    objectName: "constituencyResultCandidateTotal_" + String(modelData.candidate_id)
                    implicitHeight: candidateRow.implicitHeight + 24
                    RowLayout {
                        id: candidateRow
                        anchors.fill: parent
                        anchors.margins: 12
                        Label {
                            Layout.fillWidth: true
                            text: modelData.ballot_number + " · " + modelData.name
                            textFormat: Text.PlainText
                            color: "#25344b"
                            wrapMode: Text.WordWrap
                        }
                        Label {
                            objectName: "constituencyResultCandidateVotes_" + String(modelData.candidate_id)
                            text: page.exact(modelData, "quantity")
                            textFormat: Text.PlainText
                            font.pixelSize: 18
                            font.weight: Font.Medium
                            color: "#25344b"
                        }
                    }
                }
            }
        }
    }

    FormPanel {
        objectName: "constituencyResultsPendingPanel"
        visible: (page.result.pending || []).length > 0
        implicitHeight: pendingColumn.implicitHeight + 40
        ColumnLayout {
            id: pendingColumn
            anchors.fill: parent
            anchors.margins: 20
            spacing: 10
            Heading { text: page.t("constituency_results_pending") }
            Repeater {
                model: page.result.pending || []
                delegate: FormCaption {
                    required property var modelData
                    required property int index
                    objectName: "constituencyResultPending_" + index
                    Layout.fillWidth: true
                    text: page.pendingLabel(modelData)
                    color: "#8a5c16"
                }
            }
        }
    }

    Repeater {
        model: page.result.contributions || []
        delegate: FormPanel {
            required property var modelData
            objectName: "constituencyResultContribution_" + String(modelData.scope_id)
            Layout.fillWidth: true
            implicitHeight: contributionColumn.implicitHeight + 40
            ColumnLayout {
                id: contributionColumn
                anchors.fill: parent
                anchors.margins: 20
                spacing: 12
                Heading {
                    text: page.t("constituency_results_contributions") + " · "
                        + page.t("constituency_results_scope") + " #" + modelData.scope_id
                }
                GridLayout {
                    Layout.fillWidth: true
                    columns: page.width > 760 ? 3 : 1
                    columnSpacing: 12
                    rowSpacing: 10
                    Detail {
                        caption: page.t("constituency_results_station")
                        value: "#" + modelData.station_id
                    }
                    Detail {
                        caption: page.t("constituency_results_scope_revision")
                        value: String(modelData.scope_revision)
                    }
                    Detail {
                        caption: page.t("constituency_results_round")
                        value: String(modelData.round_number) + " · #" + modelData.round_id
                    }
                    Detail {
                        caption: page.t("constituency_results_round_revision")
                        value: String(modelData.round_revision)
                    }
                    Detail {
                        caption: page.t("constituency_results_selection_revision")
                        value: String(modelData.selection_revision)
                    }
                }
                FormCaption { text: page.t("constituency_results_source_boxes") }
                Repeater {
                    model: modelData.frozen_source_context.box_basis || []
                    delegate: Label {
                        required property var modelData
                        objectName: "constituencyResultBox_" + String(modelData.id)
                        Layout.fillWidth: true
                        text: page.t("constituency_results_box_reference") + " "
                            + (modelData.box_reference || ("#" + modelData.id)) + " · "
                            + page.t("constituency_results_box_revision") + " " + modelData.revision
                            + " · " + page.t("constituency_results_box_origin") + " "
                            + page.stationLabel(modelData.origin) + " · "
                            + page.t("constituency_results_box_destination") + " "
                            + page.stationLabel(modelData.destination) + " · "
                            + page.t("constituency_results_box_status") + " "
                            + page.sourceStatus(modelData.status)
                        textFormat: Text.PlainText
                        wrapMode: Text.WrapAnywhere
                        color: "#25344b"
                    }
                }
                FormCaption { text: page.t("constituency_results_accounting") }
                Repeater {
                    model: modelData.frozen_source_context.accounting_basis || []
                    delegate: ColumnLayout {
                        required property var modelData
                        objectName: "constituencyResultAccounting_" + String(modelData.id)
                        Layout.fillWidth: true
                        spacing: 4
                        Label {
                            text: page.stationLabel(modelData.context.station) + " · "
                                + page.t("constituency_results_accounting_id") + " " + modelData.id
                                + " · " + page.t("constituency_results_accounting_revision") + " "
                                + modelData.revision + " · "
                                + page.t("constituency_results_accounting_status") + " "
                                + page.sourceStatus(modelData.status)
                            textFormat: Text.PlainText
                            wrapMode: Text.WrapAnywhere
                            color: "#25344b"
                            Layout.fillWidth: true
                        }
                        Label {
                            text: page.t("constituency_results_source_current") + ": "
                                + (modelData.source_current ? page.t("constituency_results_yes")
                                    : page.t("constituency_results_no"))
                                + " · " + page.t("constituency_results_approval_valid") + ": "
                                + (modelData.approval_valid ? page.t("constituency_results_yes")
                                    : page.t("constituency_results_no"))
                                + " · " + page.t("constituency_results_stock_estimate") + ": "
                                + page.exact(modelData.summary || ({}), "estimated_box_from_stock_quantity")
                                + " · " + page.t("constituency_results_turnout_estimate") + ": "
                                + page.exact(modelData.summary || ({}), "estimated_box_from_turnout_quantity")
                            textFormat: Text.PlainText
                            wrapMode: Text.WrapAnywhere
                            color: "#52647d"
                            Layout.fillWidth: true
                        }
                    }
                }
                FormCaption {
                    objectName: "constituencyResultVotesCaption_" + String(modelData.scope_id)
                    text: page.t("constituency_results_candidate_votes")
                }
                Repeater {
                    model: modelData.final_candidate_votes || []
                    delegate: Label {
                        required property var modelData
                        text: modelData.name + " · " + page.exact(modelData, "quantity")
                        textFormat: Text.PlainText
                        color: "#25344b"
                        Layout.fillWidth: true
                    }
                }
            }
        }
    }

    FormPanel {
        objectName: "constituencyResultsTiePanel"
        visible: (page.result.tie_candidate_ids || []).length > 1
        implicitHeight: tieColumn.implicitHeight + 40
        ColumnLayout {
            id: tieColumn
            anchors.fill: parent
            anchors.margins: 20
            spacing: 12
            Heading { text: page.t("constituency_results_tie_action") }
            FormCaption { text: page.t("constituency_results_tie_hint") }
            FormCaption {
                visible: page.uncertain
                text: page.t("unsaved_tie_resolution")
                color: "#8a5c16"
            }
            ComboBox {
                id: tieCandidatePicker
                objectName: "constituencyResultTieCandidate"
                Layout.fillWidth: true
                model: page.tieRows
                textRole: "label"
                displayText: currentIndex >= 0 ? currentText
                    : page.t("constituency_results_choose_candidate")
                currentIndex: page.selectedCandidateIndex()
                enabled: page.canEdit
                Accessible.name: page.t("constituency_results_choose_candidate")
                onActiveFocusChanged: if (activeFocus) Qt.callLater(function() {
                    if (tieCandidatePicker.activeFocus) page.reveal(tieCandidatePicker)
                })
                onActivated: index => {
                    if (index >= 0 && index < page.tieRows.length)
                        page.results.setResolutionCandidate(page.tieRows[index].candidate_id)
                }
            }
            FormCaption { text: page.t("constituency_results_reason_required") }
            TextArea {
                id: tieReasonField
                objectName: "constituencyResultTieReason"
                Layout.fillWidth: true
                implicitHeight: Math.max(88, contentHeight + topPadding + bottomPadding)
                text: page.editorState.reason || ""
                placeholderText: text.length ? "" : page.t("constituency_results_reason_placeholder")
                leftPadding: 12
                rightPadding: 12
                topPadding: 12
                bottomPadding: 12
                topInset: 0
                textFormat: TextEdit.PlainText
                wrapMode: TextEdit.WordWrap
                clip: true
                selectByMouse: true
                enabled: page.canEdit
                readOnly: !enabled
                Accessible.name: page.t("constituency_results_reason_required")
                onTextChanged: if (activeFocus) page.results.setResolutionReason(text)
                onActiveFocusChanged: if (activeFocus) Qt.callLater(function() {
                    if (tieReasonField.activeFocus) page.reveal(tieReasonField)
                })
                background: Rectangle {
                    radius: 8
                    color: "white"
                    border.color: tieReasonField.activeFocus ? "#1967d2" : "#a7b2c2"
                    border.width: tieReasonField.activeFocus ? 2 : 1
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Action {
                    objectName: "constituencyResultResolveTie"
                    visible: !page.uncertain
                    text: page.t("constituency_results_resolve")
                    highlighted: true
                    enabled: page.canEdit && !!page.editorState.selected_candidate_id
                        && !!(page.editorState.reason || "").trim()
                    onClicked: passwordDialog.open()
                }
                Action {
                    objectName: "constituencyResultRetryTie"
                    visible: page.uncertain
                    text: page.t("constituency_results_retry")
                    highlighted: true
                    enabled: !page.working
                    onClicked: passwordDialog.open()
                }
                Action {
                    objectName: "constituencyResultDiscard"
                    visible: !!page.editorState.dirty && !page.uncertain
                    text: page.t("constituency_results_discard")
                    highlighted: false
                    enabled: !page.working
                    onClicked: discardDialog.open()
                }
            }
        }
    }

    FormPanel {
        objectName: "constituencyResultsDecisionHistoryPanel"
        visible: (page.result.resolution_history || []).length > 0
        implicitHeight: historyColumn.implicitHeight + 40
        ColumnLayout {
            id: historyColumn
            anchors.fill: parent
            anchors.margins: 20
            spacing: 12
            Heading { text: page.t("constituency_results_decision_history") }
            Repeater {
                model: page.result.resolution_history || []
                delegate: FormPanel {
                    required property var modelData
                    objectName: "constituencyResultDecision_" + String(modelData.revision)
                    implicitHeight: decisionColumn.implicitHeight + 24
                    ColumnLayout {
                        id: decisionColumn
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: 6
                        Detail {
                            caption: page.t("constituency_results_resolution_revision")
                            value: String(modelData.revision)
                        }
                        Detail {
                            caption: page.t("constituency_results_resolved_candidate")
                            value: page.candidateName(modelData.candidate_id)
                        }
                        Detail {
                            caption: page.t("constituency_results_reason")
                            value: modelData.reason
                        }
                        Detail {
                            caption: page.t("constituency_results_reviewer")
                            value: String(modelData.actor_id)
                        }
                        Detail {
                            caption: page.t("constituency_results_resolved_at")
                            value: page.results.formatTime(modelData.accepted_at)
                        }
                        Detail {
                            caption: page.t("constituency_results_basis_digest")
                            value: modelData.basis_digest
                        }
                        Detail {
                            valueObjectName: "constituencyResultsDecisionCurrent_" + modelData.revision
                            caption: page.t("constituency_results_is_current")
                            value: modelData.is_current ? page.t("constituency_results_yes")
                                : page.t("constituency_results_no")
                        }
                        Detail {
                            valueObjectName: "constituencyResultsDecisionValid_" + modelData.revision
                            caption: page.t("constituency_results_is_valid")
                            value: modelData.valid ? page.t("constituency_results_yes")
                                : page.t("constituency_results_no")
                        }
                    }
                }
            }
        }
    }

    ConstituencyRecountsPanel {
        recounts: page.results.recounts
        texts: page.words
        onReveal: control => page.reveal(control)
    }

    FormPanel {
        objectName: "constituencyResultsReportPanel"
        visible: !!page.result.basis_digest
        implicitHeight: reportColumn.implicitHeight + 40
        ColumnLayout {
            id: reportColumn
            anchors.fill: parent
            anchors.margins: 20
            spacing: 12
            Heading { text: page.t("constituency_results_report") }
            GridLayout {
                Layout.fillWidth: true
                columns: page.width > 800 ? 3 : 1
                columnSpacing: 12
                rowSpacing: 10
                Action {
                    objectName: "constituencyResultPreview"
                    text: page.t("constituency_results_preview")
                    enabled: !page.reportBlocked
                    onClicked: page.results.preview(page.locale)
                }
                Action {
                    objectName: "constituencyResultExportPdf"
                    text: page.t("constituency_results_export_pdf")
                    enabled: !page.reportBlocked
                    onClicked: page.exportReport("pdf")
                }
                Action {
                    objectName: "constituencyResultExportCsv"
                    text: page.t("constituency_results_export_csv")
                    enabled: !page.reportBlocked
                    onClicked: page.exportReport("csv")
                }
            }
            Label {
                objectName: "constituencyResultReportPreview"
                visible: page.editorState.report.locale === page.locale
                text: page.editorState.report_text || ""
                textFormat: Text.PlainText
                wrapMode: Text.WrapAnywhere
                color: "#25344b"
                Layout.fillWidth: true
            }
            FormCaption {
                visible: !!page.editorState.export_path
                text: page.editorState.export_path || ""
            }
        }
    }

    Dialog {
        id: passwordDialog
        objectName: "constituencyResultsPasswordDialog"
        modal: true
        focus: true
        anchors.centerIn: Overlay.overlay
        width: Math.min(460, Overlay.overlay.width - 40)
        implicitWidth: Math.max(0, width)
        title: page.t("constituency_results_password_title")
        header: Label {
            text: passwordDialog.title
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            padding: 24
            bottomPadding: 0
            font.pixelSize: Material.dialogTitleFontPixelSize
        }
        onOpened: passwordField.forceActiveFocus()
        onRejected: passwordField.clear()
        onAccepted: {
            var value = passwordField.text
            passwordField.clear()
            page.results.resolveTie(value)
        }
        onClosed: passwordField.clear()
        contentItem: ColumnLayout {
            spacing: 12
            FormCaption { text: page.t("constituency_results_password_hint") }
            FormField {
                id: passwordField
                objectName: "constituencyResultsPassword"
                echoMode: TextInput.Password
                maximumLength: 128
                Accessible.name: page.t("constituency_results_password")
                onReveal: control => page.reveal(control)
            }
        }
        footer: DialogButtonBox {
            Button {
                objectName: "constituencyResultsPasswordCancel"
                text: page.t("constituency_results_cancel")
                DialogButtonBox.buttonRole: DialogButtonBox.RejectRole
            }
            Button {
                objectName: "constituencyResultsPasswordConfirm"
                text: page.t("constituency_results_confirm")
                enabled: passwordField.text.length > 0
                DialogButtonBox.buttonRole: DialogButtonBox.AcceptRole
            }
        }
    }

    Connections {
        target: page.results
        function onStateChanged() {
            var accountId = (page.editorState.context.account || {}).id || 0
            var accountChanged = page.observedAccountId && accountId !== page.observedAccountId
            page.observedAccountId = accountId
            if (!page.editorState.role || accountChanged || page.editorState.error
                    || page.editorState.notice === "constituency_tie_resolved") {
                passwordField.clear()
                if (!page.editorState.role || accountChanged
                        || page.editorState.notice === "constituency_tie_resolved")
                    passwordDialog.close()
            }
        }
    }

    ConfirmationDialog {
        id: discardDialog
        objectName: "constituencyResultDiscardDialog"
        focus: true
        message: page.t("constituency_results_discard_prompt")
        acceptLabel: page.t("constituency_results_confirm_discard")
        rejectLabel: page.t("constituency_results_keep_editing")
        onConfirmed: {
            if (!page.uncertain) page.results.discardAndReload()
        }
    }

    FileDialog {
        id: exportDialog
        objectName: "constituencyResultsExportDialog"
        fileMode: FileDialog.SaveFile
        currentFolder: StandardPaths.writableLocation(StandardPaths.DocumentsLocation)
        onAccepted: page.results.exportReport(
            page.pendingLocale, page.pendingFormat, Qt.resolvedUrl(selectedFile.toString()).toString())
    }
}
