pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts

ColumnLayout {
    id: page
    objectName: "recoveryPage"
    required property var recovery
    required property var words
    property string locale: "tc"
    property string selectedRequestId: ""
    property string pendingRetryId: ""
    readonly property var editorState: recovery.state
    readonly property var commands: editorState.commands || []
    readonly property var selectedCommand: page.commandById(page.selectedRequestId)
    readonly property bool working: !!editorState.busy || !!editorState.refreshing
    readonly property bool supervisor: editorState.role === "supervisor"
    signal reveal(var control)
    spacing: 18

    function t(key) { return words[key] || words.recovery_unknown_error || "—" }
    function commandById(requestId) {
        if (!requestId) return ({})
        for (var index = 0; index < commands.length; index++)
            if (commands[index].request_id === requestId) return commands[index]
        return ({})
    }
    function commandLabel(row) {
        return t(row.workflow || "") + " · " + page.targetLabel(row)
            + " · " + t("recovery_" + (row.status || "pending"))
    }
    function recountPath(row) {
        if (row.workflow !== "count" || row.method !== "POST") return null
        return /^\/api\/workspace\/stations\/([1-9][0-9]*)\/counting-scopes\/([1-9][0-9]*)\/recounts$/.exec(String(row.path || ""))
    }
    function recountReceipt(row) {
        if (!page.recountPath(row)) return ({})
        var record = page.receiptRecord(row)
        return record.instruction && record.round ? record : ({})
    }
    function wideRecountPath(row) {
        if (row.workflow !== "constituency_recount" || row.method !== "POST") return null
        return /^\/api\/workspace\/constituencies\/([1-9][0-9]*)\/recounts$/.exec(String(row.path || ""))
    }
    function wideRecountReceipt(row) {
        if (!page.wideRecountPath(row)) return ({})
        var record = page.receiptRecord(row)
        return record.instruction && Array.isArray(record.members) ? record : ({})
    }
    function instructionPath(row) {
        return page.recountPath(row) || page.wideRecountPath(row)
    }
    function targetLabel(row) {
        var wide = page.wideRecountPath(row)
        if (wide) {
            var parent = page.wideRecountReceipt(row).instruction || ({})
            return page.t("recovery_constituency") + " #" + wide[1]
                + (parent.id ? " · " + page.t("recovery_constituency_instruction")
                    + " #" + page.exact(parent, "id") : "")
        }
        var recount = page.recountPath(row)
        if (recount) {
            var instruction = page.recountReceipt(row).instruction || ({})
            return page.t("recovery_recount_instruction")
                + (instruction.id ? " #" + page.exact(instruction, "id") : "")
                + " · " + page.t("recovery_scope") + " #" + recount[2]
                + (instruction.new_round_id
                    ? " · " + page.t("recovery_recount_new_round") + " #"
                        + page.exact(instruction, "new_round_id") : "")
        }
        var target = String(row.target || "")
        var path = target || String(row.path || "")
        var parts = path.split("/")
        if (row.workflow === "count") {
            var scopeAt = parts.indexOf("counting-scopes")
            var roundsAt = parts.indexOf("rounds")
            if (scopeAt >= 0 && roundsAt >= 0)
                return page.t("recovery_scope") + " #" + (parts[scopeAt + 1] || "—")
                    + " · " + page.t("recovery_round") + " #" + (parts[roundsAt + 1] || "—")
        }
        if (row.workflow === "turnout") {
            var turnoutAt = parts.indexOf("turnout")
            if (turnoutAt >= 0)
                return page.t("recovery_period") + " #" + (parts[turnoutAt + 1] || "—")
        }
        if (row.workflow === "allocation") {
            var allocationAt = parts.indexOf("allocations")
            if (allocationAt >= 0)
                return allocationAt + 1 < parts.length
                    ? page.t("recovery_allocation") + " #" + parts[allocationAt + 1]
                    : page.t("recovery_new_allocation")
        }
        return page.t("recovery_target_not_recorded")
    }
    function eventTime(row) {
        var payload = row.payload || ({})
        var value = payload.event_at || payload.original_event_at || ""
        return value ? page.recovery.formatTime(value)
            : page.t("recovery_no_event_time")
    }
    function receiptRecord(row) {
        var receipt = row.receipt || ({})
        return receipt.record || ({})
    }
    function receiptStatus(value) {
        return value === "recorded" ? page.t("recovery_recorded")
            : page.t(value || "recovery_unknown_error")
    }
    function blankReceiptSummary(round) {
        return page.t("recovery_recount_new_round") + " #" + page.exact(round, "id")
            + " · " + page.t("recovery_round") + " #" + page.exact(round, "round_number")
            + " · " + page.t("recovery_receipt_revision") + " " + page.exact(round, "revision")
            + " · " + page.receiptStatus(round.status)
    }
    function receiptSummary(row) {
        var record = page.receiptRecord(row)
        if (!Object.keys(record).length) return page.t("recovery_no_receipt")
        var wide = page.wideRecountReceipt(row)
        if (wide.instruction) {
            var parts = [page.t("recovery_constituency_member_count") + " "
                + page.exact(wide.instruction, "member_count")]
            for (var member of wide.members)
                parts.push(page.blankReceiptSummary(member.round || ({})))
            return parts.join("\n")
        }
        var recount = page.recountReceipt(row)
        if (recount.round) {
            return page.blankReceiptSummary(recount.round)
        }
        if (row.workflow === "count")
            return page.t("recovery_round") + " #" + (record.round_number || "—")
                + " · " + page.t("recovery_revision") + " " + (record.revision || "—")
                + " · " + page.receiptStatus(record.status)
        if (row.workflow === "allocation")
            return page.t("recovery_allocation") + " #" + (record.id || "—")
                + " · " + page.t("recovery_revision") + " " + (record.revision || "—")
                + " · " + page.t("recovery_quantity") + " "
                + page.exact(record, "quantity")
        if (row.workflow === "turnout")
            return page.t("recovery_period") + " #" + (record.period_index || "—")
                + " · " + page.t("recovery_revision") + " " + (record.revision || "—")
                + " · " + page.receiptStatus(record.status)
        return page.t("recovery_no_receipt")
    }
    function exact(row, key) {
        var value = row[key + "_display"]
        if (value !== undefined) return value
        return row[key] === undefined || row[key] === null ? "—" : String(row[key])
    }
    function selectedStatus() { return selectedCommand.status || "" }
    function canCheck(row) {
        return !!row.request_id && !page.working
            && (row.status === "pending" || row.status === "uncertain")
    }
    function canRetry(row) {
        return !!row.request_id && !page.working
            && row.status === "uncertain" && row.error === "request_not_found"
    }
    function retry(row) {
        if (!page.canRetry(row)) return
        if (row.confirmation_required) {
            pendingRetryId = row.request_id
            passwordDialog.open()
        } else {
            page.recovery.retry(row.request_id, "")
        }
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
        Layout.fillWidth: true
        spacing: 4
        FormCaption { text: detail.caption }
        Label {
            text: detail.value
            textFormat: Text.PlainText
            color: "#25344b"
            wrapMode: Text.WrapAnywhere
            Layout.fillWidth: true
        }
    }

    RowLayout {
        Layout.fillWidth: true
        Heading { objectName: "recoveryTitle"; text: page.t("recovery_title"); font.pixelSize: 28 }
        BusyIndicator {
            running: page.working
            visible: running
            implicitWidth: 28
            implicitHeight: 28
            Accessible.name: page.t("recovery_loading")
        }
        FormButton {
            objectName: "recoveryReload"
            text: page.t("recovery_refresh")
            flat: true
            highlighted: false
            working: page.working
            enabled: !page.working
            onClicked: page.recovery.reload()
            onReveal: control => page.reveal(control)
        }
    }
    Label {
        Layout.fillWidth: true
        text: page.t("recovery_intro")
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
        color: "#52647d"
    }
    FormNotice {
        objectName: "recoveryNotice"
        words: page.words
        error: page.editorState.error
        notice: page.editorState.notice
        onReveal: control => page.reveal(control)
    }
    FormCaption {
        objectName: "recoveryEmpty"
        visible: !page.working && !page.commands.length
        text: page.t("recovery_empty")
    }
    FormCaption {
        visible: !!page.commands.length
        text: page.t("recovery_manual_compare")
    }

    FormPanel {
        objectName: "recoveryCommandsPanel"
        visible: !!page.commands.length
        implicitHeight: commandsColumn.implicitHeight + 40
        ColumnLayout {
            id: commandsColumn
            anchors.fill: parent
            anchors.margins: 20
            spacing: 10
            Heading { text: page.t("recovery_commands") }
            Repeater {
                model: page.commands
                delegate: Action {
                    required property var modelData
                    required property int index
                    objectName: "recoveryCommand_" + modelData.request_id
                    text: page.commandLabel(modelData)
                    highlighted: modelData.request_id === page.selectedRequestId
                    onClicked: page.selectedRequestId = modelData.request_id
                }
            }
        }
    }

    FormPanel {
        objectName: "recoverySelectedCommandPanel"
        visible: !!page.selectedCommand.request_id
        implicitHeight: commandColumn.implicitHeight + 40
        ColumnLayout {
            id: commandColumn
            anchors.fill: parent
            anchors.margins: 20
            spacing: 12
            Heading { text: page.commandLabel(page.selectedCommand) }
            GridLayout {
                Layout.fillWidth: true
                columns: page.width > 760 ? 2 : 1
                columnSpacing: 16
                rowSpacing: 10
                Detail {
                    caption: page.t("recovery_request_id")
                    value: page.selectedCommand.request_id || "—"
                }
                Detail {
                    caption: page.t("recovery_workflow")
                    value: page.t(page.selectedCommand.workflow || "recovery_unknown_error")
                }
                Detail {
                    caption: page.t("recovery_target")
                    value: page.targetLabel(page.selectedCommand)
                }
                Detail {
                    caption: page.t("recovery_method")
                    value: page.t(page.selectedCommand.method || "recovery_unknown_error")
                }
                Detail {
                    caption: page.t("recovery_created_at")
                    value: page.recovery.formatTime(page.selectedCommand.created_at || "")
                }
                Detail {
                    caption: page.instructionPath(page.selectedCommand)
                        ? page.t("recovery_recount_original_event_at") : page.t("recovery_event_at")
                    value: page.eventTime(page.selectedCommand)
                }
                Detail {
                    caption: page.t("recovery_status")
                    value: page.t("recovery_" + (page.selectedCommand.status || "pending"))
                }
                Detail {
                    visible: !!page.selectedCommand.error
                    caption: page.t("recovery_error")
                    value: page.t(page.selectedCommand.error)
                }
            }
            FormNotice {
                visible: !!page.selectedCommand.error
                words: page.words
                error: page.selectedCommand.error || ""
                onReveal: control => page.reveal(control)
            }
            FormCaption {
                objectName: "recoveryReceiptSummary"
                visible: !!page.selectedCommand.receipt
                text: (page.instructionPath(page.selectedCommand)
                    ? page.t("recovery_original_receipt") : page.t("recovery_receipt"))
                    + " · " + page.receiptSummary(page.selectedCommand)
            }
            FormCaption {
                objectName: "recoveryReceiptHistoryHint"
                visible: !!page.recountReceipt(page.selectedCommand).round
                    || !!page.wideRecountReceipt(page.selectedCommand).instruction
                text: page.wideRecountPath(page.selectedCommand)
                    ? page.t("recovery_constituency_receipt_hint")
                    : page.t("recovery_original_receipt_hint")
            }
            RowLayout {
                Layout.fillWidth: true
                Action {
                    objectName: "recoveryCheckOutcome"
                    text: page.t("recovery_check_outcome")
                    enabled: page.canCheck(page.selectedCommand)
                    onClicked: page.recovery.checkOutcome(page.selectedCommand.request_id)
                }
                Action {
                    objectName: "recoveryRetryOriginal"
                    text: page.t("recovery_retry")
                    visible: page.canRetry(page.selectedCommand)
                    enabled: page.canRetry(page.selectedCommand)
                    onClicked: page.retry(page.selectedCommand)
                }
            }
            FormCaption {
                visible: page.selectedCommand.status === "uncertain"
                    && page.selectedCommand.error !== "request_not_found"
                text: page.t("recovery_manual_compare")
                color: "#8a5c16"
            }
        }
    }

    Dialog {
        id: passwordDialog
        objectName: "recoveryPasswordDialog"
        modal: true
        focus: true
        anchors.centerIn: Overlay.overlay
        width: Math.min(460, (Overlay.overlay ? Overlay.overlay.width : 500) - 40)
        implicitWidth: Math.max(0, width)
        title: page.t("recovery_retry_password")
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
            var password = passwordField.text
            passwordField.clear()
            page.recovery.retry(page.pendingRetryId, password)
        }
        onClosed: {
            passwordField.clear()
            page.pendingRetryId = ""
        }
        contentItem: ColumnLayout {
            spacing: 12
            FormCaption { text: page.t("recovery_password_hint") }
            FormField {
                id: passwordField
                objectName: "recoveryPassword"
                echoMode: TextInput.Password
                maximumLength: 128
                Accessible.name: page.t("recovery_password")
                onReveal: control => page.reveal(control)
            }
        }
        footer: DialogButtonBox {
            Button {
                objectName: "recoveryPasswordCancel"
                text: page.t("recovery_cancel")
                DialogButtonBox.buttonRole: DialogButtonBox.RejectRole
            }
            Button {
                objectName: "recoveryPasswordConfirm"
                text: page.t("recovery_confirm")
                enabled: passwordField.text.length > 0
                DialogButtonBox.buttonRole: DialogButtonBox.AcceptRole
            }
        }
    }

    Connections {
        target: page.recovery
        function onStateChanged() {
            if (!page.editorState.role || page.editorState.error) {
                passwordField.clear()
                if (!page.editorState.role) passwordDialog.close()
            }
        }
    }
}
