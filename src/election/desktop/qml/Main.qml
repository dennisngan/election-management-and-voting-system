import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts

ApplicationWindow {
    id: window
    visible: true
    width: 1280
    height: 800
    minimumWidth: 900
    minimumHeight: 480
    title: "Election Management and Voting System"
    color: "#f6f8fc"
    Material.theme: Material.Light
    Material.accent: "#1967d2"
    Material.primary: "#1967d2"
    font.family: Qt.platform.os === "windows" ? "Microsoft JhengHei UI" : "PingFang TC"
    font.pixelSize: 14

    readonly property var state: controller.state
    readonly property var words: controller.texts
    readonly property bool signedIn: state.phase !== "signed_out"
    readonly property color ink: "#25344b"
    readonly property color muted: "#65758b"
    readonly property color accent: "#1967d2"
    readonly property color line: "#e1e7f0"

    function t(key) { return words[key] || key }
    function submitLogin() { controller.signIn(serverField.text, usernameField.text, passwordField.text) }
    function submitPassword() { controller.changePassword(currentField.text, newField.text, confirmField.text) }
    function revealField(control) {
        if (!control || !scroll.contentItem) return
        var ancestor = control
        while (ancestor && ancestor !== scroll) ancestor = ancestor.parent
        if (ancestor !== scroll) return
        var viewport = scroll.contentItem
        var origin = control.mapToItem(viewport, 0, 0)
        var target = viewport.contentY
        if (origin.y < 12) target += origin.y - 12
        else if (origin.y + control.height > viewport.height - 12)
            target += origin.y + control.height - viewport.height + 12
        viewport.contentY = Math.max(0, Math.min(target,
            Math.max(0, viewport.contentHeight - viewport.height)))
    }

    Connections {
        target: controller
        function onEraseSecrets() {
            passwordField.clear()
            currentField.clear()
            newField.clear()
            confirmField.clear()
        }
    }

    component Caption: Label {
        color: window.muted
        font.pixelSize: 12
        wrapMode: Text.WordWrap
        textFormat: Text.PlainText
    }
    component Field: TextField {
        id: fieldControl
        Layout.fillWidth: true
        implicitHeight: 48
        selectByMouse: true
        enabled: !window.state.busy
        font.pixelSize: 14
        Material.containerStyle: Material.Outlined
        onActiveFocusChanged: if (activeFocus) Qt.callLater(function() { window.revealField(fieldControl) })
    }
    component PrimaryButton: Button {
        id: primaryControl
        highlighted: true
        implicitHeight: 48
        font.pixelSize: 14
        font.weight: Font.Medium
        enabled: !window.state.busy
        Material.roundedScale: Material.FullScale
        onActiveFocusChanged: if (activeFocus) Qt.callLater(function() { window.revealField(primaryControl) })
    }
    component Panel: Rectangle {
        color: "white"
        radius: 18
        border.color: window.line
    }
    component Detail: ColumnLayout {
        property string caption
        property string value
        spacing: 5
        Caption { text: parent.caption; Layout.fillWidth: true }
        Label {
            text: parent.value
            color: window.ink
            font.pixelSize: 15
            wrapMode: Text.WrapAnywhere
            Layout.fillWidth: true
            textFormat: Text.PlainText
        }
    }

    header: Rectangle {
        height: 88
        color: "white"
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: window.line }
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 28
            anchors.rightMargin: 28
            spacing: 16
            Rectangle {
                width: 44; height: 44; radius: 14; color: window.accent
                Label { anchors.centerIn: parent; text: "E"; font.pixelSize: 24; font.weight: Font.Medium; color: "white" }
                Accessible.ignored: true
            }
            ColumnLayout {
                Layout.fillWidth: true
                Layout.minimumWidth: 180
                Layout.maximumWidth: 480
                spacing: 3
                Label { text: window.t("app_name"); color: window.ink; font.pixelSize: 20; font.weight: Font.Medium; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                Caption { text: window.t("election_management"); font.pixelSize: 11 }
            }
            Item { Layout.fillWidth: true }
            RowLayout {
                Layout.minimumWidth: 80
                Layout.maximumWidth: 180
                spacing: 8
                Rectangle {
                    width: 7; height: 7; radius: 4
                    color: window.state.connection === "connected" ? "#238467" : "#b47716"
                    Accessible.ignored: true
                }
                Caption {
                    text: window.t(window.state.connection)
                    color: window.state.connection === "connected" ? "#238467" : window.muted
                    Layout.maximumWidth: 180
                    Layout.fillWidth: true
                }
            }
            Button {
                text: window.t("refresh")
                flat: true
                onClicked: controller.refresh()
                Accessible.name: window.t("refresh")
            }
            ComboBox {
                id: languageBox
                implicitWidth: 132
                model: [{label: "繁體中文", code: "tc"}, {label: "简体中文", code: "sc"}, {label: "English", code: "en"}]
                textRole: "label"
                valueRole: "code"
                currentIndex: window.state.locale === "sc" ? 1 : window.state.locale === "en" ? 2 : 0
                onActivated: controller.setLocale(currentValue)
                Accessible.name: window.t("language")
            }
        }
    }

    footer: Rectangle {
        height: 44
        color: "white"
        Rectangle { width: parent.width; height: 1; color: window.line }
        RowLayout {
            anchors.fill: parent; anchors.leftMargin: 24; anchors.rightMargin: 24
            Caption { text: window.t("last_refresh") + "  " + window.state.last_refresh }
            Item { Layout.fillWidth: true }
            Caption { text: window.state.clock; font.family: Qt.platform.os === "windows" ? "Consolas" : "Menlo" }
        }
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0
        Rectangle {
            id: sidebar
            visible: window.signedIn && window.state.phase === "workspace"
            Layout.preferredWidth: 208
            Layout.fillHeight: true
            color: "#edf3fc"
            ColumnLayout {
                anchors.fill: parent; anchors.margins: 18; spacing: 8
                Caption { text: window.t("workspace"); Layout.topMargin: 10; Layout.bottomMargin: 12 }
                Button {
                    text: window.t("account"); Layout.fillWidth: true
                    highlighted: true; flat: true
                    Material.background: "#dceaff"
                    Material.roundedScale: Material.FullScale
                }
                Button { text: window.t("polling"); Layout.fillWidth: true; flat: true; enabled: false }
                Button { text: window.t("counting"); Layout.fillWidth: true; flat: true; enabled: false }
                Button { text: window.t("records"); Layout.fillWidth: true; flat: true; enabled: false }
                Item { Layout.fillHeight: true }
                Caption { text: window.t("role") + " · " + window.t(window.state.account.role || ""); Layout.fillWidth: true }
                Button { text: window.t("logout"); flat: true; Layout.fillWidth: true; onClicked: controller.signOut() }
            }
        }
        ScrollView {
            id: scroll
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: availableWidth
            clip: true
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            ColumnLayout {
                width: scroll.availableWidth
                spacing: 0
                Item { Layout.preferredHeight: 24 }
                Rectangle {
                    visible: !!window.state.error || !!window.state.notice
                    onVisibleChanged: if (visible) Qt.callLater(function() { window.revealField(window.activeFocusItem) })
                    Layout.fillWidth: true
                    Layout.leftMargin: 32; Layout.rightMargin: 32; Layout.bottomMargin: 18
                    implicitHeight: messageLabel.implicitHeight + 26
                    radius: 10
                    color: window.state.error ? "#fceceb" : "#e8f5ef"
                    Label {
                        id: messageLabel
                        anchors.fill: parent; anchors.margins: 13
                        text: window.t(window.state.error || window.state.notice)
                        color: window.state.error ? "#a52c27" : "#216a50"
                        wrapMode: Text.WordWrap
                        Accessible.role: Accessible.StaticText
                        Accessible.name: text
                    }
                }

                RowLayout {
                    visible: !window.signedIn
                    Layout.fillWidth: true
                    Layout.leftMargin: 52; Layout.rightMargin: 52
                    Layout.topMargin: 12; Layout.bottomMargin: 38
                    spacing: 50
                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 250
                        Layout.maximumWidth: 500
                        spacing: 24
                        Label { text: window.t("election_management"); color: window.accent; font.pixelSize: 12; font.letterSpacing: 1.2 }
                        Label { text: window.t("tagline"); color: window.ink; font.pixelSize: 35; font.weight: Font.Medium; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                        Rectangle { Layout.preferredWidth: 44; height: 4; radius: 2; color: window.accent }
                        Caption { text: window.t("connection_detail"); font.pixelSize: 15; Layout.fillWidth: true }
                        Item { Layout.preferredHeight: 26 }
                        Detail { caption: window.t("server"); value: window.state.server_url; Layout.fillWidth: true }
                        Caption { text: window.t("no_idle_lock"); Layout.fillWidth: true }
                    }
                    Panel {
                        Layout.preferredWidth: 420
                        implicitHeight: loginLayout.implicitHeight + 56
                        ColumnLayout {
                            id: loginLayout
                            anchors.fill: parent; anchors.margins: 28; spacing: 14
                            Caption { text: window.t("staff_access"); color: window.accent }
                            Label { text: window.t("welcome"); color: window.ink; font.pixelSize: 26; font.weight: Font.Medium; Layout.bottomMargin: 8 }
                            Label { text: window.t("server_address"); color: window.muted }
                            Field {
                                id: serverField; objectName: "serverAddress"
                                Component.onCompleted: text = window.state.server_url
                                Accessible.name: window.t("server_address")
                                placeholderText: "https://server.example:8443"
                                onEditingFinished: controller.configureServer(text)
                            }
                            Label { text: window.t("username"); color: window.muted }
                            Field {
                                id: usernameField; objectName: "username"
                                Accessible.name: window.t("username")
                                onAccepted: passwordField.forceActiveFocus()
                            }
                            Label { text: window.t("password"); color: window.muted }
                            Field {
                                id: passwordField; objectName: "password"
                                echoMode: TextInput.Password
                                Accessible.name: window.t("password")
                                onAccepted: window.submitLogin()
                            }
                            PrimaryButton {
                                text: window.t(window.state.busy ? "signing_in" : "sign_in"); Layout.fillWidth: true; Layout.topMargin: 8
                                onClicked: window.submitLogin()
                            }
                            BusyIndicator { running: window.state.busy; visible: running; Layout.alignment: Qt.AlignHCenter; implicitHeight: 28; implicitWidth: 28 }
                        }
                    }
                }

                ColumnLayout {
                    visible: window.state.phase === "password_change"
                    Layout.fillWidth: true
                    Layout.leftMargin: 36; Layout.rightMargin: 36; Layout.bottomMargin: 28
                    spacing: 20
                    RowLayout {
                        Layout.fillWidth: true
                        ColumnLayout {
                            Layout.fillWidth: true
                            Caption { text: window.t("first_login"); color: window.accent }
                            Label { text: window.t("change_password"); color: window.ink; font.pixelSize: 28; font.weight: Font.Medium }
                            Caption { text: window.t("signed_in_as") + "  " + (window.state.account.display_name || ""); Layout.fillWidth: true }
                        }
                        Button { text: window.t("logout"); flat: true; onClicked: controller.signOut() }
                    }
                    Panel {
                        Layout.alignment: Qt.AlignHCenter
                        Layout.fillWidth: true; Layout.maximumWidth: 520
                        implicitHeight: changeLayout.implicitHeight + 48
                        ColumnLayout {
                            id: changeLayout
                            anchors.fill: parent; anchors.margins: 24; spacing: 12
                            Caption { text: window.t("password_hint"); Layout.fillWidth: true; Layout.bottomMargin: 6 }
                            Label { text: window.t("current_password"); color: window.muted }
                            Field { id: currentField; objectName: "currentPassword"; echoMode: TextInput.Password; Accessible.name: window.t("current_password"); onAccepted: newField.forceActiveFocus() }
                            Label { text: window.t("new_password"); color: window.muted }
                            Field { id: newField; objectName: "newPassword"; echoMode: TextInput.Password; Accessible.name: window.t("new_password"); onAccepted: confirmField.forceActiveFocus() }
                            Label { text: window.t("confirm_password"); color: window.muted }
                            Field { id: confirmField; objectName: "confirmPassword"; echoMode: TextInput.Password; Accessible.name: window.t("confirm_password"); onAccepted: window.submitPassword() }
                            PrimaryButton { text: window.t(window.state.busy ? "saving_password" : "save_password"); Layout.fillWidth: true; Layout.topMargin: 8; onClicked: window.submitPassword() }
                            BusyIndicator { running: window.state.busy; visible: running; implicitHeight: 28; implicitWidth: 28; Layout.alignment: Qt.AlignHCenter }
                        }
                    }
                }

                ColumnLayout {
                    visible: window.state.phase === "workspace"
                    Layout.fillWidth: true
                    Layout.leftMargin: 32; Layout.rightMargin: 32; Layout.bottomMargin: 28
                    spacing: 24
                    RowLayout {
                        Layout.fillWidth: true
                        ColumnLayout {
                            spacing: 6
                            Caption { text: window.t("workspace"); color: window.accent }
                            Label { text: window.t("user_profile"); color: window.ink; font.pixelSize: 28; font.weight: Font.Medium }
                        }
                        Item { Layout.fillWidth: true }
                        Rectangle {
                            radius: 16; color: "#e7f3ed"; implicitWidth: readyLabel.implicitWidth + 26; height: 32
                            Label { id: readyLabel; anchors.centerIn: parent; text: window.t("authenticated"); color: "#247355"; font.pixelSize: 12 }
                        }
                    }
                    Panel {
                        Layout.fillWidth: true
                        implicitHeight: accountLayout.implicitHeight + 48
                        GridLayout {
                            id: accountLayout
                            anchors.fill: parent; anchors.margins: 24
                            columns: 2; columnSpacing: 32; rowSpacing: 24
                            Detail { caption: window.t("account"); value: window.state.account.display_name || ""; Layout.fillWidth: true }
                            Detail { caption: window.t("username"); value: window.state.account.username || ""; Layout.fillWidth: true }
                            Detail { caption: window.t("role"); value: window.t(window.state.account.role || ""); Layout.fillWidth: true }
                            Detail { caption: window.t("session_expires"); value: window.state.expires; Layout.fillWidth: true }
                        }
                    }
                    Panel {
                        Layout.fillWidth: true
                        implicitHeight: emptyLayout.implicitHeight + 48
                        ColumnLayout {
                            id: emptyLayout
                            anchors.fill: parent; anchors.margins: 24; spacing: 12
                            Label { text: window.t("no_election"); font.pixelSize: 19; color: window.ink; font.weight: Font.Medium; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                            Caption { text: window.t("no_election_detail"); Layout.fillWidth: true; font.pixelSize: 14 }
                            Rectangle { Layout.fillWidth: true; height: 1; color: window.line; Layout.topMargin: 8; Layout.bottomMargin: 8 }
                            Detail { caption: window.t("linked_server"); value: window.state.server_url; Layout.fillWidth: true }
                            Caption { text: window.t("no_idle_lock"); Layout.fillWidth: true }
                        }
                    }
                }
                Item { Layout.preferredHeight: 12 }
            }
        }
    }
}
