pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts

ColumnLayout {
    id: panel
    required property var recounts
    required property var words
    readonly property var editorState: recounts.state
    readonly property var form: editorState.forms || ({})
    readonly property var scope: editorState.scope || ({})
    readonly property var selection: editorState.selection || ({})
    readonly property var latest: editorState.latest_instruction || ({})
    readonly property bool working: !!editorState.busy
    readonly property bool editable: !!editorState.can_instruct
    signal reveal(var control)
    Layout.fillWidth: true
    spacing: 20

    function t(key) { return words[key] || key }
    function moveFocus(control, forward) {
        var next = control.nextItemInFocusChain(forward)
        if (next) next.forceActiveFocus(forward ? Qt.TabFocusReason : Qt.BacktabFocusReason)
    }

    component Heading: Label {
        Layout.fillWidth: true
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
        color: "#25344b"
        font.pixelSize: 20
        font.weight: Font.Medium
    }

    FormPanel {
        Layout.fillWidth: true
        implicitHeight: instructionLayout.implicitHeight + 40
        ColumnLayout {
            id: instructionLayout
            anchors.fill: parent
            anchors.margins: 20
            spacing: 14
            Heading { text: panel.t("local_recount_title") }
            FormCaption { text: panel.t("local_recount_intro") }
            FormNotice {
                words: panel.words
                error: panel.editorState.error
                notice: panel.editorState.notice
                onReveal: control => panel.reveal(control)
            }
            FormCaption {
                visible: !!panel.scope.id
                text: panel.t("local_recount_scope") + " #" + (panel.scope.id || "—")
                    + " · " + panel.t("local_recount_revision") + " " + (panel.scope.revision || "—")
            }
            FormCaption {
                visible: !!panel.selection.round_id
                text: panel.t("local_recount_source") + " " + (panel.selection.round_number || "—")
                    + " · " + panel.t("local_recount_revision") + " "
                    + (panel.selection.round_revision || "—")
            }
            FormCaption {
                visible: !panel.editable && !panel.latest.id && !panel.working
                text: panel.t("local_recount_not_ready")
            }
            ColumnLayout {
                visible: panel.editorState.role === "supervisor" && !!panel.editorState.scope_id
                Layout.fillWidth: true
                spacing: 12
                FormCaption { text: panel.t("local_recount_event_at") }
                FormField {
                    objectName: "localRecountEventTime"
                    text: panel.form.event_at || ""
                    maximumLength: 32
                    readOnly: !panel.editable
                    working: panel.working
                    Accessible.name: panel.t("local_recount_event_at")
                    onTextEdited: panel.recounts.setField("event_at", text)
                    onReveal: control => panel.reveal(control)
                }
                FormCaption { text: panel.t("local_recount_event_hint") }
                FormCaption { text: panel.t("local_recount_reason") }
                TextArea {
                    id: reasonField
                    objectName: "localRecountReason"
                    Layout.fillWidth: true
                    implicitHeight: Math.max(92, contentHeight + topPadding + bottomPadding)
                    readOnly: !panel.editable
                    enabled: !panel.working
                    text: panel.form.reason || ""
                    textFormat: TextEdit.PlainText
                    wrapMode: TextEdit.WordWrap
                    selectByMouse: true
                    clip: true
                    leftPadding: 12; rightPadding: 12; topPadding: 12; bottomPadding: 12
                    topInset: 0; bottomInset: 0
                    Accessible.name: panel.t("local_recount_reason")
                    onTextChanged: if (text !== (panel.form.reason || ""))
                        panel.recounts.setField("reason", text)
                    Keys.priority: Keys.BeforeItem
                    Keys.onTabPressed: event => { panel.moveFocus(reasonField, true); event.accepted = true }
                    Keys.onBacktabPressed: event => { panel.moveFocus(reasonField, false); event.accepted = true }
                    onActiveFocusChanged: if (activeFocus) Qt.callLater(function() {
                        if (reasonField.activeFocus) panel.reveal(reasonField)
                    })
                    background: Rectangle {
                        radius: 8
                        color: "white"
                        border.color: reasonField.activeFocus ? "#1967d2" : "#a7b2c2"
                        border.width: reasonField.activeFocus ? 2 : 1
                    }
                }
                FormCaption { text: panel.t("local_recount_reason_hint") }
                FormButton {
                    objectName: "localRecountInstruct"
                    Layout.fillWidth: true
                    text: panel.t("local_recount_instruct")
                    enabled: panel.editable && !!panel.form.event_at
                        && !!panel.form.reason && panel.form.reason.trim().length > 0
                        && panel.form.reason.length <= 2000
                    working: panel.working
                    onClicked: passwordDialog.open()
                    onReveal: control => panel.reveal(control)
                }
            }
            RowLayout {
                Layout.fillWidth: true
                FormButton {
                    objectName: "localRecountRefresh"
                    Layout.fillWidth: true
                    text: panel.t("local_recount_refresh")
                    enabled: !panel.working && !panel.editorState.refreshing
                    onClicked: panel.recounts.refresh()
                    onReveal: control => panel.reveal(control)
                }
                FormButton {
                    objectName: "localRecountDiscard"
                    Layout.fillWidth: true
                    text: panel.t("local_recount_discard")
                    enabled: !!panel.editorState.dirty && !panel.working
                        && !panel.editorState.refreshing && !panel.editorState.uncertain_save
                    onClicked: instructionDiscard.open()
                    onReveal: control => panel.reveal(control)
                }
            }
            FormButton {
                objectName: "localRecountCheckOutcome"
                Layout.fillWidth: true
                visible: !!panel.editorState.uncertain_save
                text: panel.t("local_recount_check")
                enabled: !panel.working && !panel.editorState.refreshing
                onClicked: panel.recounts.checkOutcome()
                onReveal: control => panel.reveal(control)
            }
            FormCaption {
                visible: !!panel.editorState.uncertain_save
                text: panel.t("local_recount_request_id") + " · "
                    + (panel.editorState.pending_request_id || "—")
            }
        }
    }
    FormPanel {
        visible: !!panel.latest.id
        Layout.fillWidth: true
        implicitHeight: latestLayout.implicitHeight + 40
        ColumnLayout {
            id: latestLayout
            anchors.fill: parent
            anchors.margins: 20
            spacing: 12
            Heading { text: panel.t("local_recount_latest") }
            FormCaption {
                text: panel.t("local_recount_round") + " " + (panel.latest.new_round_number || "—")
                    + " · " + panel.t("local_recount_status_" + (panel.latest.status || "pending"))
            }
            FormCaption {
                text: panel.t(panel.editorState.pending
                    ? "local_recount_current_pending" : "local_recount_current_satisfied")
            }
            FormCaption { text: panel.latest.reason || "" }
            FormCaption {
                text: panel.t("local_recount_event_at") + " · "
                    + panel.recounts.formatTime(panel.latest.event_at || "")
            }
            FormCaption {
                text: panel.t("local_recount_entered_at") + " · "
                    + panel.recounts.formatTime(panel.latest.entered_at || "")
            }
            FormCaption {
                text: panel.t("local_recount_actor") + " · " + (panel.latest.actor_id || "—")
            }
        }
    }
    Connections {
        target: panel.recounts
        function onInstructed() {
            passwordField.clear()
            passwordDialog.close()
        }
        function onStateChanged() {
            if (!panel.editorState.scope_id || panel.editorState.role !== "supervisor") {
                passwordField.clear()
                passwordDialog.close()
                instructionDiscard.close()
            }
        }
    }
    ConfirmationDialog {
        id: instructionDiscard
        objectName: "localRecountDiscardDialog"
        title: panel.t("local_recount_discard")
        message: panel.t("local_recount_discard_hint")
        acceptLabel: panel.t("discard_changes")
        rejectLabel: panel.t("keep_editing")
        onConfirmed: panel.recounts.discardAndReload()
    }
    Dialog {
        id: passwordDialog
        objectName: "localRecountPasswordDialog"
        modal: true
        focus: true
        anchors.centerIn: Overlay.overlay
        width: Math.min(520, Overlay.overlay.width - 40)
        implicitWidth: Math.max(0, width)
        title: panel.t("local_recount_confirm_title")
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
        onClosed: passwordField.clear()
        onAccepted: {
            var credential = passwordField.text
            passwordField.clear()
            panel.recounts.instruct(credential)
        }
        contentItem: ColumnLayout {
            spacing: 12
            FormCaption { text: panel.t("local_recount_confirm_hint") }
            FormField {
                id: passwordField
                objectName: "localRecountPassword"
                echoMode: TextInput.Password
                maximumLength: 128
                Accessible.name: panel.t("local_recount_password")
                onReveal: control => panel.reveal(control)
            }
        }
        footer: DialogButtonBox {
            Button {
                objectName: "localRecountPasswordCancel"
                text: panel.t("local_recount_cancel")
                DialogButtonBox.buttonRole: DialogButtonBox.RejectRole
            }
            Button {
                objectName: "localRecountPasswordConfirm"
                text: panel.t("local_recount_confirm")
                enabled: passwordField.text.length > 0 && panel.editable
                DialogButtonBox.buttonRole: DialogButtonBox.AcceptRole
            }
        }
    }
}
