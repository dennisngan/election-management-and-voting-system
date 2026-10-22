import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: page
    required property var config
    required property var words
    readonly property var editorState: config.state
    property string pendingKind: ""
    property int pendingId: 0
    property string observedError: ""
    property bool stationMode: false
    signal reveal(var control)
    function t(key) { return words[key] || key }
    function choose(kind, recordId) {
        if (editorState.busy) return
        if (!config.load(kind, recordId, false)) {
            pendingKind = kind
            pendingId = recordId
            discardDialog.open()
        }
    }
    spacing: 20
    RowLayout {
        Layout.fillWidth: true
        Label { text: page.t(page.stationMode ? "station_setup" : "election_setup"); font.pixelSize: 28; font.weight: Font.Medium; color: "#25344b"; Layout.fillWidth: true; wrapMode: Text.WordWrap }
        BusyIndicator { running: page.editorState.busy || page.editorState.refreshing; visible: running; implicitWidth: 28; implicitHeight: 28; Accessible.name: page.t("loading") }
        Button { text: page.t("refresh"); flat: true; enabled: !page.editorState.busy && !page.editorState.refreshing; onClicked: page.config.refresh() }
    }
    Rectangle {
        id: message
        visible: !!page.editorState.error || !!page.editorState.notice
        Layout.fillWidth: true
        implicitHeight: messageText.implicitHeight + 28
        radius: 10
        color: page.editorState.error ? "#fceceb" : "#e8f5ef"
        Label {
            id: messageText
            anchors.fill: parent; anchors.margins: 14
            text: page.t(page.editorState.error || page.editorState.notice)
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            color: page.editorState.error ? "#a52c27" : "#216a50"
            Accessible.role: Accessible.StaticText
            Accessible.name: text
        }
    }
    Connections {
        target: page.config
        function onStateChanged() {
            var error = page.config.state.error
            if (page.visible && error && error !== page.observedError)
                Qt.callLater(function() { page.reveal(message) })
            page.observedError = error
        }
    }
    Label { visible: page.stationMode; text: page.t("station_setup_hint"); color: "#65758b"; Layout.fillWidth: true; wrapMode: Text.WordWrap }
    ConfigurationSection {
        kind: "election"; config: page.config; words: page.words; editorState: page.editorState
        editAllowed: !page.stationMode
        onChoose: (kind, recordId) => page.choose(kind, recordId)
        onReveal: control => page.reveal(control)
    }
    GridLayout {
        Layout.fillWidth: true
        columns: page.width > 850 && !page.stationMode ? 2 : 1
        columnSpacing: 20; rowSpacing: 20
        ConfigurationSection {
            kind: "constituency"; config: page.config; words: page.words; editorState: page.editorState
            parentReady: !!page.editorState.selected.election.id
            editAllowed: !page.stationMode
            onChoose: (kind, recordId) => page.choose(kind, recordId)
            onReveal: control => page.reveal(control)
        }
        ConfigurationSection {
            visible: !page.stationMode
            kind: "candidate"; config: page.config; words: page.words; editorState: page.editorState
            parentReady: !!page.editorState.selected.constituency.id
            onChoose: (kind, recordId) => page.choose(kind, recordId)
            onReveal: control => page.reveal(control)
        }
    }
    GridLayout {
        visible: page.stationMode
        Layout.fillWidth: true
        columns: page.width > 850 ? 2 : 1
        columnSpacing: 20; rowSpacing: 20
        ConfigurationSection {
            kind: "station"; config: page.config; words: page.words; editorState: page.editorState
            parentReady: !!page.editorState.selected.constituency.id
            onChoose: (kind, recordId) => page.choose(kind, recordId)
            onReveal: control => page.reveal(control)
        }
        ConfigurationSection {
            kind: "counter"; config: page.config; words: page.words; editorState: page.editorState
            parentReady: !!page.editorState.selected.station.id
            onChoose: (kind, recordId) => page.choose(kind, recordId)
            onReveal: control => page.reveal(control)
        }
    }
    Dialog {
        id: discardDialog
        title: page.t("discard_changes")
        modal: true
        anchors.centerIn: Overlay.overlay
        width: Math.min(460, Overlay.overlay.width - 40)
        contentItem: Label { text: page.t("unsaved_changes"); textFormat: Text.PlainText; wrapMode: Text.WordWrap }
        footer: DialogButtonBox {
            Button { text: page.t("keep_editing"); DialogButtonBox.buttonRole: DialogButtonBox.RejectRole }
            Button { text: page.t("discard_changes"); DialogButtonBox.buttonRole: DialogButtonBox.AcceptRole }
        }
        onAccepted: page.config.load(page.pendingKind, page.pendingId, true)
    }
}
