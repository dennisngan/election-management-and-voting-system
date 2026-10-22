pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: page
    required property var staff
    required property var words
    readonly property var editorState: staff.state
    readonly property var form: editorState.form
    readonly property bool hasSelectedAccount: !!editorState.selected.id
    readonly property var roleCodes: ["administrator", "polling_officer", "counting_officer", "supervisor"]
    property int pendingAccountId: 0
    signal reveal(var control)
    spacing: 20

    function t(key) { return words[key] || key }
    function accountLabel(row) { return row.username + " · " + row.display_name }
    function selectedIndex() {
        for (var i = 0; i < editorState.accounts.length; i++)
            if (editorState.accounts[i].id === editorState.selected.id) return i
        return -1
    }
    function roleIndex() { return roleCodes.indexOf(form.role) }
    function chooseAccount(accountId) {
        if (editorState.busy) return
        if (!staff.loadAccount(accountId, false)) {
            pendingAccountId = accountId
            discardDialog.open()
        }
    }
    function stationLabel(context) {
        return context.election.name + " · " + context.constituency.code + " · "
            + context.constituency.name + "\n" + context.station.code + " · " + context.station.name
    }
    function pad(value) { return value < 10 ? "0" + value : String(value) }
    function hongKongTime(value) {
        var parsed = new Date(value)
        if (isNaN(parsed.getTime())) return "—"
        var hkt = new Date(parsed.getTime() + 8 * 60 * 60 * 1000)
        return hkt.getUTCFullYear() + "-" + pad(hkt.getUTCMonth() + 1) + "-"
            + pad(hkt.getUTCDate()) + " " + pad(hkt.getUTCHours()) + ":"
            + pad(hkt.getUTCMinutes()) + ":" + pad(hkt.getUTCSeconds()) + " HKT"
    }

    Connections {
        target: page.staff
        function onErasePassword() {
            temporaryPassword.clear()
            temporaryConfirmation.clear()
            resetPassword.clear()
            resetConfirmation.clear()
        }
    }

    RowLayout {
        Layout.fillWidth: true
        Label {
            text: page.t("staff_accounts")
            textFormat: Text.PlainText
            color: "#25344b"
            font.pixelSize: 28
            font.weight: Font.Medium
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }
        BusyIndicator {
            running: page.editorState.busy || page.editorState.refreshing
            visible: running
            implicitWidth: 28
            implicitHeight: 28
            Accessible.name: page.t(page.editorState.busy ? "saving" : "loading")
        }
        FormButton {
            text: page.t("refresh")
            flat: true
            highlighted: false
            working: page.editorState.busy || page.editorState.refreshing
            onClicked: page.staff.refresh()
            onReveal: control => page.reveal(control)
        }
    }

    FormNotice {
        words: page.words
        error: page.editorState.error
        notice: page.editorState.notice
        onReveal: control => page.reveal(control)
    }

    FormPanel {
        implicitHeight: pickerLayout.implicitHeight + 40
        ColumnLayout {
            id: pickerLayout
            anchors.fill: parent
            anchors.margins: 20
            spacing: 12
            RowLayout {
                Layout.fillWidth: true
                FormCaption { text: page.t("select_account") }
                FormButton {
                    text: page.t("new_account")
                    flat: true
                    highlighted: false
                    working: page.editorState.busy
                    onClicked: page.chooseAccount(0)
                    onReveal: control => page.reveal(control)
                }
            }
            ComboBox {
                id: accountPicker
                objectName: "staffAccountPicker"
                Layout.fillWidth: true
                visible: page.editorState.accounts.length > 0
                enabled: !page.editorState.busy
                model: page.editorState.accounts
                textRole: "display_name"
                currentIndex: page.selectedIndex()
                displayText: currentIndex >= 0
                    ? page.accountLabel(model[currentIndex]) : page.t("select_account")
                Accessible.name: page.t("select_account")
                contentItem: Text {
                    text: accountPicker.displayText
                    textFormat: Text.PlainText
                    color: "#25344b"
                    font: accountPicker.font
                    elide: Text.ElideRight
                    verticalAlignment: Text.AlignVCenter
                }
                delegate: ItemDelegate {
                    id: accountDelegate
                    required property var modelData
                    required property int index
                    width: accountPicker.width
                    text: page.accountLabel(modelData)
                    highlighted: accountPicker.highlightedIndex === index
                    contentItem: Text {
                        text: accountDelegate.text
                        textFormat: Text.PlainText
                        color: "#25344b"
                        elide: Text.ElideRight
                        verticalAlignment: Text.AlignVCenter
                    }
                }
                onActivated: {
                    page.chooseAccount(model[currentIndex].id)
                    // Keep the picker on the current form if discarding is cancelled.
                    currentIndex = Qt.binding(function() { return page.selectedIndex() })
                }
                onActiveFocusChanged: if (activeFocus)
                    Qt.callLater(function() { page.reveal(accountPicker) })
            }
            FormCaption {
                visible: page.editorState.accounts.length === 0
                text: page.t(page.editorState.refreshing ? "loading" : "no_accounts")
            }
        }
    }

    GridLayout {
        visible: page.editorState.editing
        Layout.fillWidth: true
        columns: page.width > 900 ? 2 : 1
        columnSpacing: 20
        rowSpacing: 20

        FormPanel {
            Layout.alignment: Qt.AlignTop
            implicitHeight: accountForm.implicitHeight + 40
            ColumnLayout {
                id: accountForm
                anchors.fill: parent
                anchors.margins: 20
                spacing: 12
                RowLayout {
                    Layout.fillWidth: true
                    FormCaption {
                        text: page.hasSelectedAccount
                            ? page.t("revision") + " " + page.editorState.selected.revision
                                + (page.editorState.dirty ? " •" : "")
                            : page.t("editing_new")
                    }
                    FormButton {
                        visible: page.hasSelectedAccount
                        text: page.t("reload_saved")
                        flat: true
                        highlighted: false
                        working: page.editorState.busy
                        onClicked: page.chooseAccount(page.editorState.selected.id)
                        onReveal: control => page.reveal(control)
                    }
                }
                FormCaption { text: page.t("username") }
                FormField {
                    objectName: "staffUsername"
                    text: page.form.username
                    readOnly: page.hasSelectedAccount
                    maximumLength: 64
                    working: page.editorState.busy
                    Accessible.name: page.t("username")
                    onTextEdited: page.staff.setField("username", text)
                    onReveal: control => page.reveal(control)
                }
                FormCaption { text: page.t("display_name") }
                FormField {
                    objectName: "staffDisplayName"
                    text: page.form.display_name
                    maximumLength: 120
                    working: page.editorState.busy
                    Accessible.name: page.t("display_name")
                    onTextEdited: page.staff.setField("display_name", text)
                    onReveal: control => page.reveal(control)
                }
                FormCaption { text: page.t("role") }
                ComboBox {
                    id: rolePicker
                    objectName: "staffRole"
                    Layout.fillWidth: true
                    enabled: !page.editorState.busy
                    model: page.roleCodes
                    currentIndex: page.roleIndex()
                    displayText: page.t(page.form.role)
                    Accessible.name: page.t("role")
                    delegate: ItemDelegate {
                        required property string modelData
                        required property int index
                        width: rolePicker.width
                        text: page.t(modelData)
                        highlighted: rolePicker.highlightedIndex === index
                    }
                    onActivated: {
                        page.staff.setField("role", model[currentIndex])
                        currentIndex = Qt.binding(function() { return page.roleIndex() })
                    }
                    onActiveFocusChanged: if (activeFocus)
                        Qt.callLater(function() { page.reveal(rolePicker) })
                }
                CheckBox {
                    id: enabledBox
                    objectName: "staffEnabled"
                    text: page.t("account_enabled")
                    checked: page.form.enabled
                    enabled: !page.editorState.busy
                    Accessible.name: text
                    onToggled: {
                        page.staff.setEnabled(checked)
                        checked = Qt.binding(function() { return page.form.enabled })
                    }
                    onActiveFocusChanged: if (activeFocus)
                        Qt.callLater(function() { page.reveal(enabledBox) })
                }
                FormCaption {
                    visible: page.hasSelectedAccount && page.editorState.selected.must_change_password
                    text: page.t("password_change_required")
                }
                ColumnLayout {
                    visible: !page.hasSelectedAccount
                    Layout.fillWidth: true
                    spacing: 12
                    FormCaption { text: page.t("temporary_password") }
                    FormField {
                        id: temporaryPassword
                        objectName: "staffTemporaryPassword"
                        echoMode: TextInput.Password
                        maximumLength: 128
                        working: page.editorState.busy
                        Accessible.name: page.t("temporary_password")
                        onReveal: control => page.reveal(control)
                    }
                    FormCaption { text: page.t("confirm_temporary_password") }
                    FormField {
                        id: temporaryConfirmation
                        objectName: "staffTemporaryConfirmation"
                        echoMode: TextInput.Password
                        maximumLength: 128
                        working: page.editorState.busy
                        Accessible.name: page.t("confirm_temporary_password")
                        onReveal: control => page.reveal(control)
                    }
                    FormCaption { text: page.t("min_password") }
                }
                FormCaption {
                    visible: page.hasSelectedAccount
                    text: page.t("staff_changes_hint")
                }
                FormButton {
                    objectName: "staffSave"
                    Layout.fillWidth: true
                    text: page.t(page.editorState.busy ? "saving" : "save_account")
                    working: page.editorState.busy
                    enabled: !working && (!page.hasSelectedAccount || page.editorState.dirty)
                    onClicked: page.hasSelectedAccount
                        ? page.staff.save("", "")
                        : page.staff.save(temporaryPassword.text, temporaryConfirmation.text)
                    onReveal: control => page.reveal(control)
                }
            }
        }

        FormPanel {
            Layout.alignment: Qt.AlignTop
            implicitHeight: assignments.implicitHeight + 40
            ColumnLayout {
                id: assignments
                anchors.fill: parent
                anchors.margins: 20
                spacing: 12
                Label {
                    text: page.t("station_assignments")
                    textFormat: Text.PlainText
                    color: "#25344b"
                    font.pixelSize: 20
                    font.weight: Font.Medium
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }
                FormCaption {
                    visible: page.form.role === "administrator"
                    text: page.t("invalid_station_assignment")
                }
                FormCaption {
                    visible: page.editorState.station_options.length === 0
                    text: page.t(page.editorState.refreshing ? "loading" : "no_station_options")
                }
                Repeater {
                    model: page.editorState.station_options
                    delegate: CheckBox {
                        id: assignmentBox
                        required property var modelData
                        Layout.fillWidth: true
                        text: page.stationLabel(modelData)
                        checked: page.form.station_ids.indexOf(modelData.station.id) >= 0
                        enabled: !page.editorState.busy && page.form.role !== "administrator"
                        Accessible.name: text
                        contentItem: Text {
                            text: assignmentBox.text
                            textFormat: Text.PlainText
                            font: assignmentBox.font
                            color: assignmentBox.enabled ? "#25344b" : "#8190a3"
                            leftPadding: assignmentBox.indicator.width + assignmentBox.spacing
                            verticalAlignment: Text.AlignVCenter
                            wrapMode: Text.WordWrap
                        }
                        onToggled: {
                            page.staff.setStationAssigned(modelData.station.id, checked)
                            checked = Qt.binding(function() {
                                return page.form.station_ids.indexOf(assignmentBox.modelData.station.id) >= 0
                            })
                        }
                        onActiveFocusChanged: if (activeFocus)
                            Qt.callLater(function() { page.reveal(assignmentBox) })
                    }
                }
            }
        }
    }

    FormPanel {
        visible: page.editorState.editing && page.hasSelectedAccount
        implicitHeight: resetForm.implicitHeight + 40
        ColumnLayout {
            id: resetForm
            anchors.fill: parent
            anchors.margins: 20
            spacing: 12
            Label {
                text: page.t("reset_password")
                textFormat: Text.PlainText
                color: "#25344b"
                font.pixelSize: 20
                font.weight: Font.Medium
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
            FormCaption { text: page.t("reset_password_hint") }
            GridLayout {
                Layout.fillWidth: true
                columns: page.width > 900 ? 2 : 1
                columnSpacing: 20
                rowSpacing: 12
                ColumnLayout {
                    Layout.fillWidth: true
                    FormCaption { text: page.t("temporary_password") }
                    FormField {
                        id: resetPassword
                        objectName: "staffResetPassword"
                        echoMode: TextInput.Password
                        maximumLength: 128
                        working: page.editorState.busy
                        Accessible.name: page.t("temporary_password")
                        onReveal: control => page.reveal(control)
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    FormCaption { text: page.t("confirm_temporary_password") }
                    FormField {
                        id: resetConfirmation
                        objectName: "staffResetConfirmation"
                        echoMode: TextInput.Password
                        maximumLength: 128
                        working: page.editorState.busy
                        Accessible.name: page.t("confirm_temporary_password")
                        onReveal: control => page.reveal(control)
                    }
                }
            }
            FormButton {
                objectName: "staffReset"
                text: page.t(page.editorState.busy ? "saving" : "reset_password")
                working: page.editorState.busy
                Layout.alignment: Qt.AlignLeft
                onClicked: page.staff.resetPassword(resetPassword.text, resetConfirmation.text)
                onReveal: control => page.reveal(control)
            }
        }
    }

    FormPanel {
        visible: page.editorState.editing && page.hasSelectedAccount
        implicitHeight: auditLayout.implicitHeight + 40
        ColumnLayout {
            id: auditLayout
            anchors.fill: parent
            anchors.margins: 20
            spacing: 12
            Label {
                text: page.t("audit_history")
                textFormat: Text.PlainText
                color: "#25344b"
                font.pixelSize: 20
                font.weight: Font.Medium
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
            FormCaption {
                visible: page.editorState.audit.length === 0
                text: page.t(page.editorState.refreshing ? "loading" : "no_audit_events")
            }
            Repeater {
                model: page.editorState.audit
                delegate: ColumnLayout {
                    id: auditEntry
                    required property var modelData
                    Layout.fillWidth: true
                    spacing: 4
                    Label {
                        text: page.t(auditEntry.modelData.action)
                        textFormat: Text.PlainText
                        color: "#25344b"
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }
                    FormCaption {
                        text: page.hongKongTime(auditEntry.modelData.occurred_at) + " · "
                            + page.t("revision") + " " + auditEntry.modelData.details.revision
                    }
                }
            }
        }
    }

    ConfirmationDialog {
        id: discardDialog
        title: page.t("discard_changes")
        message: page.t("unsaved_changes")
        acceptLabel: page.t("discard_changes")
        rejectLabel: page.t("keep_editing")
        onAccepted: page.staff.loadAccount(page.pendingAccountId, true)
    }
}
