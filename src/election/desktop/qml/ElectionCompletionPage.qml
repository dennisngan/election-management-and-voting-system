pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts

ColumnLayout {
    id: page
    objectName: "electionCompletionPage"
    required property var completion
    required property var words
    required property string locale
    signal reveal(var control)

    readonly property var editorState: completion ? (completion.state || ({})) : ({})
    readonly property var assessment: editorState.assessment || ({})
    readonly property var election: editorState.election
        && editorState.election.id === editorState.election_id
        ? editorState.election : assessed ? assessment.election : ({})
    readonly property var history: editorState.history || ({})
    readonly property var reopeningReview: editorState.reopening_review || ({})
    readonly property bool hasReopeningReview: !!reopeningReview.election_id
    readonly property var historyEvents: history.events || []
    readonly property var blockers: assessed ? (assessment.blockers || []) : []
    readonly property bool working: !!editorState.busy || !!editorState.refreshing
    readonly property bool hasElection: Number(editorState.election_id || 0) > 0
    readonly property bool assessed: assessment.election !== undefined
        && assessment.election !== null
        && assessment.election.id === editorState.election_id
    readonly property bool ready: editorState.can_finalize === true
    readonly property string errorCode: String(editorState.error || "")
    spacing: 20

    function t(key) { return (words && words[key]) || key }
    function messageText(code) {
        return (words && words[code])
            || (words && words["constituency_results_pending_" + code])
            || t("request_failed")
    }
    function electionText() {
        if (!hasElection) return t("no_election")
        var name = String(election.name || "")
        var reference = "#" + String(election.id || editorState.election_id)
        return name ? name + " · " + reference : reference
    }
    function statusText() {
        if (!hasElection) return t("no_election")
        if (errorCode) return messageText(errorCode)
        if (!assessed) return t("loading")
        if (election.status === "finalized") return t("election_completion_finalized")
        return t(ready ? "election_completion_ready" : "election_completion_not_ready")
    }
    function blockerText(row) {
        var text = messageText(String(row.code || ""))
        if (row.station_id !== undefined && row.station_id !== null)
            text += " · " + t("election_completion_station") + " #" + String(row.station_id)
        else if (row.constituency_id !== undefined && row.constituency_id !== null)
            text += " · " + t("recovery_constituency") + " #" + String(row.constituency_id)
        if (row.scope_id !== undefined && row.scope_id !== null)
            text += " · " + t("constituency_results_scope") + " #" + String(row.scope_id)
        if (row.box_ids && row.box_ids.length > 0)
            text += " · " + t("constituency_results_boxes") + " " + row.box_ids.join(", ")
        return text
    }

    function historyIndex() {
        for (var i = 0; i < historyEvents.length; i++)
            if (historyEvents[i].id === editorState.selected_event_id) return i
        return -1
    }
    function eventLabel(event) {
        return t("election_completion_" + event.kind) + " #" + String(event.id)
            + " · " + t("election_completion_revision") + " " + String(event.election_revision)
            + " · " + String((editorState.history_event_times || ({}))[String(event.id)] || "—")
    }
    function currentHistoryText() {
        var current = history.election || ({})
        if (!current.id) return ""
        return t("election_completion_current") + " · " + String(current.name || "")
            + " · " + t(current.status) + " · " + t("election_completion_revision")
            + " " + String(current.revision)
    }

    component Heading: Label {
        textFormat: Text.PlainText
        color: "#25344b"
        font.pixelSize: 28
        font.weight: Font.Medium
        wrapMode: Text.WordWrap
        Layout.fillWidth: true
    }

    RowLayout {
        Layout.fillWidth: true
        Heading {
            objectName: "electionCompletionTitle"
            text: page.t("election_completion_title")
        }
        BusyIndicator {
            objectName: "electionCompletionBusy"
            running: page.working
            visible: running
            implicitWidth: 28
            implicitHeight: 28
            Accessible.name: page.t("loading")
        }
        FormButton {
            objectName: "electionCompletionRefresh"
            text: page.t("refresh")
            flat: true
            highlighted: false
            enabled: page.hasElection && !page.working
            Accessible.name: text
            onClicked: page.completion.refresh()
            onReveal: control => page.reveal(control)
        }
    }

    ColumnLayout {
        Layout.fillWidth: true
        spacing: 4
        FormCaption { text: page.t("selected_election") }
        Label {
            objectName: "electionCompletionElection"
            text: page.electionText()
            textFormat: Text.PlainText
            color: "#25344b"
            font.pixelSize: 14
            wrapMode: Text.WrapAnywhere
            Layout.fillWidth: true
        }
    }

    Rectangle {
        Layout.fillWidth: true
        implicitHeight: assessmentLayout.implicitHeight + 32
        color: "white"
        radius: 16
        border.color: "#e1e7f0"

        ColumnLayout {
            id: assessmentLayout
            anchors.fill: parent
            anchors.margins: 16
            spacing: 12

            Label {
                objectName: "electionCompletionStatus"
                text: page.statusText()
                textFormat: Text.PlainText
                color: page.errorCode ? "#a13b30"
                    : !page.assessed ? "#65758b"
                    : page.ready ? "#247355" : "#805b12"
                font.pixelSize: 16
                font.weight: Font.Medium
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
                Accessible.name: text
            }

            Repeater {
                model: page.blockers
                delegate: FormCaption {
                    id: blockerLabel
                    required property var modelData
                    required property int index
                    objectName: blockerLabel.modelData.station_id !== undefined
                        && blockerLabel.modelData.station_id !== null
                        ? "electionCompletionBlocker_" + String(blockerLabel.modelData.station_id)
                        : "electionCompletionBlocker_global_" + String(blockerLabel.index)
                    text: page.blockerText(blockerLabel.modelData)
                    color: "#805b12"
                    font.pixelSize: 14
                    Accessible.name: text
                }
            }
        }
    }

    FormButton {
        objectName: "electionCompletionFinalize"
        text: page.t("election_completion_finalize")
        enabled: page.ready && !page.working && !page.editorState.uncertain_save
            && !page.editorState.reviewing
        Accessible.name: text
        onClicked: {
            if (page.completion.prepareFinalization()) passwordDialog.open()
        }
        onReveal: control => page.reveal(control)
    }

    RowLayout {
        Layout.fillWidth: true
        Heading { text: page.t("election_completion_history") }
        FormButton {
            objectName: "electionCompletionHistoryRefresh"
            text: page.t("refresh")
            flat: true
            highlighted: false
            enabled: page.hasElection && !page.working
            onClicked: page.completion.loadHistory()
            onReveal: control => page.reveal(control)
        }
    }

    FormCaption {
        objectName: "electionCompletionHistoryCurrent"
        visible: !!page.history.election
        text: page.currentHistoryText()
    }

    ColumnLayout {
        Layout.fillWidth: true
        spacing: 8
        FormCaption { text: page.t("election_completion_event") }
        ComboBox {
            id: historyPicker
            objectName: "electionCompletionHistoryEvent"
            Layout.fillWidth: true
            enabled: page.historyEvents.length > 0 && !page.working
            model: page.historyEvents.map(event => page.eventLabel(event))
            currentIndex: page.historyIndex()
            Accessible.name: page.t("election_completion_event")
            contentItem: Text {
                text: historyPicker.displayText
                textFormat: Text.PlainText
                font: historyPicker.font
                color: "#25344b"
                elide: Text.ElideRight
                verticalAlignment: Text.AlignVCenter
            }
            delegate: ItemDelegate {
                id: eventDelegate
                required property string modelData
                required property int index
                width: historyPicker.width
                text: modelData
                highlighted: historyPicker.highlightedIndex === index
                contentItem: Text {
                    text: eventDelegate.text
                    textFormat: Text.PlainText
                    color: "#25344b"
                    font: eventDelegate.font
                    wrapMode: Text.WordWrap
                    verticalAlignment: Text.AlignVCenter
                }
            }
            onActivated: {
                page.completion.selectHistoryEvent(String(page.historyEvents[currentIndex].id))
                currentIndex = Qt.binding(function() { return page.historyIndex() })
            }
            onActiveFocusChanged: if (activeFocus)
                Qt.callLater(function() { page.reveal(historyPicker) })
        }
        FormButton {
            objectName: "electionCompletionPreview"
            text: page.t("election_completion_preview")
            enabled: !!page.editorState.selected_event_id && !page.working
            onClicked: page.completion.preview(page.locale)
            onReveal: control => page.reveal(control)
        }
    }

    Label {
        objectName: "electionCompletionReportPreview"
        Layout.fillWidth: true
        visible: !!page.editorState.report_text
            && (page.editorState.report || ({})).locale === page.locale
        text: visible ? page.editorState.report_text : ""
        textFormat: Text.PlainText
        wrapMode: Text.WrapAnywhere
        color: "#25344b"
        font.pixelSize: 14
    }

    ColumnLayout {
        Layout.fillWidth: true
        visible: page.election.status === "finalized"
        spacing: 12
        Heading { text: page.t("election_completion_reopen") }
        FormCaption { text: page.t("election_completion_reopen_hint") }
        FormCaption { text: page.t("election_completion_reopen_reason") }
        FormField {
            id: reopenReason
            objectName: "electionCompletionReopenReason"
            Layout.fillWidth: true
            maximumLength: 2000
            enabled: !page.working && !page.hasReopeningReview && !page.editorState.uncertain_save
            Accessible.name: page.t("election_completion_reopen_reason")
            onReveal: control => page.reveal(control)
        }
        FormButton {
            objectName: "electionCompletionReopen"
            text: page.t("election_completion_reopen")
            enabled: !!page.editorState.can_reopen && reopenReason.text.trim().length > 0
                && !page.working && !page.hasReopeningReview && !page.editorState.uncertain_save
            onClicked: {
                if (page.completion.prepareReopening(reopenReason.text)) reopenDialog.open()
            }
            onReveal: control => page.reveal(control)
        }
    }

    Dialog {
        id: reopenDialog
        objectName: "electionCompletionReopenPasswordDialog"
        modal: true
        focus: true
        anchors.centerIn: Overlay.overlay
        width: Math.min(460, Overlay.overlay.width - 40)
        implicitWidth: Math.max(0, width)
        title: page.t("election_completion_reopen_confirm")
        header: Label {
            text: reopenDialog.title
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            padding: 24
            bottomPadding: 0
            font.pixelSize: Material.dialogTitleFontPixelSize
        }
        onOpened: reopenPassword.forceActiveFocus()
        onRejected: page.completion.cancelReopening()
        onAccepted: {
            var value = reopenPassword.text
            var reason = String(page.reopeningReview.reason || "")
            reopenPassword.clear()
            page.completion.reopen(reason, value)
        }
        onClosed: {
            reopenPassword.clear()
            page.completion.cancelReopening()
        }
        contentItem: ColumnLayout {
            spacing: 12
            FormCaption {
                text: page.electionText() + " · " + page.t("election_completion_revision")
                    + " " + String(page.reopeningReview.expected_election_revision || "")
                    + " · #" + String(page.reopeningReview.previous_finalization_id || "")
            }
            FormCaption { text: String(page.reopeningReview.reason || "") }
            FormCaption { text: page.t("election_completion_reopen_password_hint") }
            FormCaption {
                objectName: "electionCompletionReopenChanged"
                visible: !!page.editorState.reopening_changed
                text: page.t("election_completion_review_changed")
                color: "#a13b30"
            }
            FormField {
                id: reopenPassword
                objectName: "electionCompletionReopenPassword"
                echoMode: TextInput.Password
                maximumLength: 128
                Accessible.name: page.t("election_completion_password")
                onReveal: control => page.reveal(control)
            }
        }
        footer: DialogButtonBox {
            Button {
                objectName: "electionCompletionReopenCancel"
                text: page.t("election_completion_cancel")
                DialogButtonBox.buttonRole: DialogButtonBox.RejectRole
            }
            Button {
                objectName: "electionCompletionReopenConfirm"
                text: page.t("election_completion_reopen_confirm")
                enabled: reopenPassword.text.length > 0 && page.hasReopeningReview
                    && !page.working && !page.editorState.reopening_changed
                DialogButtonBox.buttonRole: DialogButtonBox.AcceptRole
            }
        }
    }

    Dialog {
        id: passwordDialog
        objectName: "electionCompletionPasswordDialog"
        modal: true
        focus: true
        anchors.centerIn: Overlay.overlay
        width: Math.min(460, Overlay.overlay.width - 40)
        implicitWidth: Math.max(0, width)
        title: page.t("election_completion_confirm_title")
        header: Label {
            text: passwordDialog.title
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            padding: 24
            bottomPadding: 0
            font.pixelSize: Material.dialogTitleFontPixelSize
        }
        onOpened: passwordField.forceActiveFocus()
        onRejected: page.completion.cancelReview()
        onAccepted: {
            var value = passwordField.text
            passwordField.clear()
            page.completion.finalize(value)
        }
        onClosed: {
            passwordField.clear()
            page.completion.cancelReview()
        }
        contentItem: ColumnLayout {
            spacing: 12
            FormCaption { text: page.t("election_completion_password_hint") }
            FormCaption {
                objectName: "electionCompletionReviewChanged"
                visible: !!page.editorState.newer_basis
                text: page.t("election_completion_review_changed")
                color: "#a13b30"
            }
            FormField {
                id: passwordField
                objectName: "electionCompletionPassword"
                echoMode: TextInput.Password
                maximumLength: 128
                Accessible.name: page.t("election_completion_password")
                onReveal: control => page.reveal(control)
            }
        }
        footer: DialogButtonBox {
            Button {
                objectName: "electionCompletionPasswordCancel"
                text: page.t("election_completion_cancel")
                DialogButtonBox.buttonRole: DialogButtonBox.RejectRole
            }
            Button {
                objectName: "electionCompletionPasswordConfirm"
                text: page.t("election_completion_finalize")
                enabled: passwordField.text.length > 0 && !!page.editorState.reviewing
                    && !page.working && !page.editorState.newer_basis
                DialogButtonBox.buttonRole: DialogButtonBox.AcceptRole
            }
        }
    }

    Connections {
        target: page.completion
        function onStateChanged() {
            if (page.editorState.reopening_changed) reopenPassword.clear()
            if (!page.hasReopeningReview) {
                reopenPassword.clear()
                reopenDialog.close()
            }
            if (page.editorState.newer_basis) passwordField.clear()
            if (!page.editorState.reviewing) {
                passwordField.clear()
                passwordDialog.close()
            }
        }
    }
}
