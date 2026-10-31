pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts

ColumnLayout {
    id: panel
    objectName: "constituencyRecountPanel"
    required property var recounts
    required property var texts
    readonly property var editorState: recounts && recounts.state ? recounts.state : ({})
    readonly property var form: editorState.forms || ({})
    readonly property var sources: editorState.scope_sources || []
    readonly property var instructions: editorState.instructions || []
    readonly property bool working: !!editorState.busy
    readonly property bool loading: working || !!editorState.refreshing
    readonly property bool unknown: !!editorState.uncertain_save
    readonly property bool newer: !!editorState.newer_basis
    readonly property bool supervisor: (editorState.role || "") === "supervisor"
    readonly property bool hasContext: !!editorState.constituency_id
    readonly property bool editable: supervisor && hasContext && !working && !unknown
    readonly property bool fieldsEditable: editable && !newer
    readonly property bool canInstruct: editable && !loading && !newer
        && !!editorState.can_instruct
        && String(form.event_at || "").trim().length > 0
        && String(form.reason || "").trim().length > 0
        && String(form.reason || "").length <= 2000
    property string observedContext: ""
    property string confirmationContext: ""
    property string discardContext: ""
    signal reveal(var control)
    Layout.fillWidth: true
    spacing: 20

    function t(key) { return (panel.texts && panel.texts[key]) || "—" }
    function exact(value) {
        return value === undefined || value === null || value === "" ? "—" : String(value)
    }
    function formattedTime(value) {
        return value ? panel.recounts.formatTime(String(value))
            : panel.t("constituency_recount_not_recorded")
    }
    function contextIdentity() {
        var context = panel.editorState.context || ({})
        var account = context.account || ({})
        var station = context.station || ({})
        return JSON.stringify([
            panel.editorState.constituency_id || 0,
            panel.editorState.account_id || account.id || 0,
            panel.editorState.station_id || station.id || 0,
            panel.editorState.role || "",
            panel.editorState.server_url || ""
        ])
    }
    function closePasswordConfirmation() {
        panel.confirmationContext = ""
        if (passwordField) passwordField.clear()
        if (passwordDialog && passwordDialog.visible) passwordDialog.close()
    }
    function closeConfirmations() {
        panel.closePasswordConfirmation()
        panel.discardContext = ""
        if (discardDialog && discardDialog.visible) discardDialog.close()
    }
    function moveFocus(control, forward) {
        var next = control.nextItemInFocusChain(forward)
        if (next) next.forceActiveFocus(forward ? Qt.TabFocusReason : Qt.BacktabFocusReason)
    }
    function stationLabel(row) {
        var source = row.source_context || ({})
        var context = source.context || ({})
        var station = context.station || ({})
        var name = (station.code || "") + (station.name ? " · " + station.name : "")
        return panel.t("constituency_recount_station") + " #" + panel.exact(row.station_id)
            + (name ? " · " + name : "")
    }
    function scopeLabel(row) {
        var source = row.source_context || ({})
        return panel.t("constituency_recount_scope") + " #" + panel.exact(row.scope_id)
            + (source.scope_reference ? " · " + source.scope_reference : "")
    }
    function sourceLabel(row) {
        return panel.t("constituency_recount_source_round_record") + " #"
            + panel.exact(row.source_round_id) + " · "
            + panel.t("constituency_recount_revision") + " "
            + panel.exact(row.source_round_revision) + " · "
            + panel.t("constituency_recount_selection_revision") + " "
            + panel.exact(row.expected_selection_revision)
    }

    component Heading: Label {
        Layout.fillWidth: true
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
        color: "#25344b"
        font.pixelSize: 20
        font.weight: Font.Medium
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
            wrapMode: Text.WrapAnywhere
            color: "#25344b"
            Layout.fillWidth: true
        }
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
        onReveal: control => panel.reveal(control)
    }

    FormPanel {
        implicitHeight: entryColumn.implicitHeight + 40
        ColumnLayout {
            id: entryColumn
            anchors.fill: parent
            anchors.margins: 20
            spacing: 14
            Heading {
                objectName: "constituencyRecountTitle"
                text: panel.t("constituency_recount_title")
            }
            FormCaption { text: panel.t("constituency_recount_intro") }
            BusyIndicator {
                running: panel.loading
                visible: running
                implicitWidth: 28
                implicitHeight: 28
            }
            FormNotice {
                words: panel.texts || ({})
                error: panel.editorState.error || ""
                notice: panel.editorState.notice || ""
                autoReveal: !passwordDialog.visible && !discardDialog.visible
                onReveal: control => panel.reveal(control)
            }
            FormCaption {
                visible: panel.newer
                text: panel.t("constituency_recount_newer_basis")
                color: "#8a5c16"
            }
            FormCaption {
                visible: panel.unknown
                text: panel.t("constituency_recount_unknown_hint")
                color: "#8a5c16"
            }
            Detail {
                visible: !!panel.editorState.pending_request_id
                caption: panel.t("constituency_recount_request_id")
                value: panel.exact(panel.editorState.pending_request_id)
            }
            FormCaption {
                visible: !panel.loading && !panel.unknown && !panel.editorState.can_instruct
                text: panel.t("constituency_recount_not_ready")
            }
            Heading { text: panel.t("constituency_recount_sources") }
            FormCaption {
                visible: panel.sources.length > 0
                text: panel.t("constituency_recount_sources_count") + " · "
                    + String(panel.sources.length)
            }
            FormCaption { text: panel.t("constituency_recount_sources_hint") }
            Repeater {
                model: panel.sources
                delegate: FormPanel {
                    id: sourceCard
                    required property var modelData
                    objectName: "constituencyRecountSource_" + String(modelData.scope_id)
                    implicitHeight: sourceColumn.implicitHeight + 24
                    ColumnLayout {
                        id: sourceColumn
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: 6
                        FormCaption { text: panel.stationLabel(sourceCard.modelData) }
                        Heading {
                            text: panel.scopeLabel(sourceCard.modelData)
                            font.pixelSize: 16
                        }
                        FormCaption {
                            text: panel.t("constituency_recount_scope_revision") + " "
                                + panel.exact(sourceCard.modelData.scope_revision)
                        }
                        FormCaption { text: panel.sourceLabel(sourceCard.modelData) }
                    }
                }
            }
            ColumnLayout {
                visible: panel.supervisor && panel.hasContext
                Layout.fillWidth: true
                spacing: 12
                FormCaption { text: panel.t("constituency_recount_time") }
                FormField {
                    objectName: "constituencyRecountEventAt"
                    text: panel.form.event_at || ""
                    maximumLength: 32
                    readOnly: !panel.fieldsEditable
                    working: panel.working
                    Accessible.name: panel.t("constituency_recount_time")
                    onTextEdited: panel.recounts.setField("event_at", text)
                    onReveal: control => panel.reveal(control)
                }
                FormCaption { text: panel.t("constituency_recount_time_hint") }
                FormCaption { text: panel.t("constituency_recount_reason") }
                TextArea {
                    id: reasonField
                    objectName: "constituencyRecountReason"
                    Layout.fillWidth: true
                    implicitHeight: Math.max(92, contentHeight + topPadding + bottomPadding)
                    readOnly: !panel.fieldsEditable
                    enabled: !panel.working
                    text: panel.form.reason || ""
                    textFormat: TextEdit.PlainText
                    wrapMode: TextEdit.WordWrap
                    selectByMouse: true
                    clip: true
                    leftPadding: 12; rightPadding: 12; topPadding: 12; bottomPadding: 12
                    topInset: 0; bottomInset: 0
                    Accessible.name: panel.t("constituency_recount_reason")
                    onTextChanged: if (text !== (panel.form.reason || ""))
                        panel.recounts.setField("reason", text)
                    Keys.priority: Keys.BeforeItem
                    Keys.onTabPressed: event => {
                        panel.moveFocus(reasonField, true); event.accepted = true
                    }
                    Keys.onBacktabPressed: event => {
                        panel.moveFocus(reasonField, false); event.accepted = true
                    }
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
                FormCaption { text: panel.t("constituency_recount_reason_hint") }
                Action {
                    objectName: "constituencyRecountInstruct"
                    text: panel.t("constituency_recount_instruct")
                    enabled: panel.canInstruct && !passwordDialog.visible
                    working: panel.working
                    onClicked: passwordDialog.open()
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Action {
                    objectName: "constituencyRecountRefresh"
                    text: panel.t("constituency_recount_refresh")
                    highlighted: false
                    enabled: panel.hasContext && !panel.loading
                    onClicked: panel.recounts.reload()
                }
                Action {
                    objectName: "constituencyRecountDiscard"
                    text: panel.t("constituency_recount_discard")
                    highlighted: false
                    enabled: panel.editable && !panel.loading && !!panel.editorState.dirty
                    onClicked: {
                        panel.discardContext = panel.contextIdentity()
                        discardDialog.open()
                    }
                }
            }
            Action {
                objectName: "constituencyRecountCheckOutcome"
                visible: panel.unknown
                text: panel.t("constituency_recount_check")
                enabled: panel.hasContext && !panel.loading
                    && !!panel.editorState.pending_request_id
                onClicked: panel.recounts.checkOutcome()
            }
        }
    }

    Heading {
        visible: panel.instructions.length > 0
        text: panel.t("constituency_recount_history")
    }
    Repeater {
        model: panel.instructions
        delegate: FormPanel {
            id: instructionCard
            required property var modelData
            readonly property var instruction: modelData || ({})
            implicitHeight: historyColumn.implicitHeight + 40
            ColumnLayout {
                id: historyColumn
                anchors.fill: parent
                anchors.margins: 20
                spacing: 12
                Heading {
                    text: panel.t("constituency_recount_instruction") + " #"
                        + panel.exact(instructionCard.instruction.id) + " · "
                        + panel.t(instructionCard.instruction.is_latest
                            ? "constituency_recount_latest" : "constituency_recount_historical")
                }
                Label {
                    text: instructionCard.instruction.reason || ""
                    textFormat: Text.PlainText
                    wrapMode: Text.WordWrap
                    color: "#25344b"
                    Layout.fillWidth: true
                }
                Detail {
                    caption: panel.t("constituency_recount_original_request_id")
                    value: panel.exact(instructionCard.instruction.request_id)
                }
                Detail {
                    caption: panel.t("constituency_recount_time")
                    value: panel.formattedTime(instructionCard.instruction.event_at)
                }
                Detail {
                    caption: panel.t("constituency_recount_entered_at")
                    value: panel.formattedTime(instructionCard.instruction.entered_at)
                }
                Detail {
                    caption: panel.t("constituency_recount_actor")
                    value: panel.exact(instructionCard.instruction.actor_id)
                }
                FormCaption {
                    text: panel.t("constituency_recount_members_completed") + " · "
                        + panel.exact(instructionCard.instruction.completed_member_count) + " / "
                        + panel.exact(instructionCard.instruction.member_count)
                }
                FormCaption {
                    text: panel.t(instructionCard.instruction.historical_complete
                        ? "constituency_recount_historical_complete"
                        : "constituency_recount_historical_pending")
                }
                FormCaption { text: panel.t("constituency_recount_history_hint") }
                Detail {
                    visible: !!instructionCard.instruction.completed_at
                    caption: panel.t("constituency_recount_completed_at")
                    value: panel.formattedTime(instructionCard.instruction.completed_at)
                }
                Repeater {
                    model: instructionCard.instruction.members || []
                    delegate: FormPanel {
                        id: memberCard
                        required property var modelData
                        readonly property var member: modelData || ({})
                        readonly property bool laterRequired: member.current_required_round_id
                            !== undefined && member.current_required_round_id !== null
                            && String(member.current_required_round_id) !== String(member.new_round_id)
                        objectName: "constituencyRecountProgress_"
                            + String(instructionCard.instruction.id) + "_" + String(member.scope_id)
                        implicitHeight: memberColumn.implicitHeight + 24
                        ColumnLayout {
                            id: memberColumn
                            anchors.fill: parent
                            anchors.margins: 12
                            spacing: 8
                            FormCaption { text: panel.stationLabel(memberCard.member) }
                            Heading {
                                text: panel.scopeLabel(memberCard.member)
                                font.pixelSize: 16
                            }
                            FormCaption {
                                text: panel.sourceLabel(memberCard.member.scope_source || ({}))
                            }
                            FormCaption {
                                text: panel.t("constituency_recount_replacement_round") + " "
                                    + panel.exact(memberCard.member.new_round_number) + " · "
                                    + panel.t("constituency_recount_record") + " #"
                                    + panel.exact(memberCard.member.new_round_id) + " · "
                                    + panel.t("constituency_recount_revision") + " "
                                    + panel.exact(memberCard.member.round_revision)
                            }
                            FormCaption {
                                text: panel.t("constituency_recount_progress_"
                                    + (memberCard.member.progress || "incomplete"))
                            }
                            Detail {
                                visible: !!memberCard.member.completed_at
                                caption: panel.t("constituency_recount_completed_at")
                                value: panel.formattedTime(memberCard.member.completed_at)
                            }
                            FormCaption {
                                visible: memberCard.member.completion_selection_revision
                                    !== undefined
                                    && memberCard.member.completion_selection_revision !== null
                                text: panel.t("constituency_recount_completion_selection") + " "
                                    + panel.exact(memberCard.member.completion_selection_revision)
                            }
                            FormCaption {
                                text: panel.t("constituency_recount_current_required") + " #"
                                    + panel.exact(memberCard.member.current_required_round_id)
                            }
                            FormCaption {
                                visible: memberCard.laterRequired
                                color: "#8a5c16"
                                text: panel.t("constituency_recount_later_required_hint")
                            }
                        }
                    }
                }
            }
        }
    }

    Component.onCompleted: panel.observedContext = panel.contextIdentity()
    Connections {
        target: panel.recounts
        function onInstructed() { panel.closeConfirmations() }
        function onStateChanged() {
            var context = panel.contextIdentity()
            var changed = panel.observedContext !== "" && panel.observedContext !== context
            panel.observedContext = context
            if (changed || !panel.supervisor || !panel.hasContext || panel.unknown)
                panel.closeConfirmations()
            else if (panel.newer)
                panel.closePasswordConfirmation()
        }
    }
    ConfirmationDialog {
        id: discardDialog
        objectName: "constituencyRecountDiscardDialog"
        title: panel.t("constituency_recount_discard")
        message: panel.t("constituency_recount_discard_hint")
        acceptLabel: panel.t("discard_changes")
        rejectLabel: panel.t("keep_editing")
        onConfirmed: if (panel.editable && !panel.loading
            && panel.discardContext === panel.contextIdentity()) {
            panel.discardContext = ""
            panel.recounts.discardDraft()
        }
    }
    Dialog {
        id: passwordDialog
        objectName: "constituencyRecountPasswordDialog"
        modal: true
        focus: true
        anchors.centerIn: Overlay.overlay
        width: Math.min(520, Overlay.overlay.width - 40)
        implicitWidth: Math.max(0, width)
        title: panel.t("constituency_recount_confirm_title")
        header: Label {
            text: passwordDialog.title
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            padding: 24
            bottomPadding: 0
            font.pixelSize: Material.dialogTitleFontPixelSize
        }
        onOpened: {
            panel.confirmationContext = panel.contextIdentity()
            passwordField.clear()
            passwordField.forceActiveFocus()
        }
        onRejected: {
            panel.confirmationContext = ""
            passwordField.clear()
        }
        onClosed: passwordField.clear()
        onAccepted: {
            var credential = passwordField.text
            var context = panel.confirmationContext
            passwordField.clear()
            panel.confirmationContext = ""
            if (credential.length > 0 && panel.canInstruct && context === panel.contextIdentity())
                panel.recounts.instruct(credential)
        }
        contentItem: ColumnLayout {
            spacing: 12
            FormCaption { text: panel.t("constituency_recount_confirm_hint") }
            FormField {
                id: passwordField
                objectName: "constituencyRecountPassword"
                echoMode: TextInput.Password
                maximumLength: 128
                Accessible.name: panel.t("constituency_recount_password")
                onReveal: control => panel.reveal(control)
            }
        }
        footer: DialogButtonBox {
            Button {
                objectName: "constituencyRecountPasswordCancel"
                text: panel.t("constituency_recount_cancel")
                DialogButtonBox.buttonRole: DialogButtonBox.RejectRole
            }
            Button {
                objectName: "constituencyRecountPasswordConfirm"
                text: panel.t("constituency_recount_confirm")
                enabled: passwordField.text.length > 0 && panel.canInstruct
                DialogButtonBox.buttonRole: DialogButtonBox.AcceptRole
            }
        }
    }
}
