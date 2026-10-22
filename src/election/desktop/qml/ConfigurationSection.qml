import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts

Rectangle {
    id: card
    required property string kind
    required property var config
    required property var words
    required property var editorState
    property bool parentReady: true
    signal choose(string kind, int recordId)
    signal reveal(var control)
    readonly property var records: editorState[kind === "election" ? "elections" : kind === "constituency" ? "constituencies" : "candidates"]
    readonly property var selected: editorState.selected[kind]
    readonly property var form: editorState.forms[kind]
    readonly property bool editing: editorState.editing[kind]
    readonly property string plural: kind === "election" ? "draft_elections" : kind === "constituency" ? "constituencies" : "candidates"
    readonly property string nameKey: kind + "_name"
    readonly property string newKey: "new_" + kind
    readonly property string saveKey: "save_" + kind
    function t(key) { return words[key] || key }
    function label(row) {
        if (!row) return ""
        return (kind === "candidate" ? row.ballot_number + " · " : kind === "constituency" ? row.code + " · " : "") + row.name
    }
    function selectedIndex() {
        for (var i = 0; i < records.length; i++) if (records[i].id === selected.id) return i
        return -1
    }
    color: "white"
    radius: 18
    border.color: "#e1e7f0"
    implicitHeight: content.implicitHeight + 40
    Layout.fillWidth: true
    Layout.alignment: Qt.AlignTop

    component Input: TextField {
        id: field
        Layout.fillWidth: true
        implicitHeight: 48
        selectByMouse: true
        enabled: !card.editorState.busy
        Material.containerStyle: Material.Outlined
        onActiveFocusChanged: if (activeFocus) Qt.callLater(function() { card.reveal(field) })
    }
    component Action: Button {
        id: action
        enabled: !card.editorState.busy
        onActiveFocusChanged: if (activeFocus) Qt.callLater(function() { card.reveal(action) })
    }
    component TextCaption: Label {
        color: "#65758b"
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
        Layout.fillWidth: true
    }

    ColumnLayout {
        id: content
        anchors.fill: parent
        anchors.margins: 20
        spacing: 12
        RowLayout {
            Layout.fillWidth: true
            Label { text: card.t(card.plural); font.pixelSize: 20; font.weight: Font.Medium; color: "#25344b"; Layout.fillWidth: true; wrapMode: Text.WordWrap }
            Action { text: card.t(card.newKey); flat: true; enabled: card.parentReady && !card.editorState.busy; onClicked: card.choose(card.kind, 0) }
        }
        TextCaption {
            visible: !card.parentReady
            text: card.t(card.kind === "candidate" ? "select_constituency" : "select_election")
        }
        ComboBox {
            id: recordPicker
            Layout.fillWidth: true
            visible: card.parentReady && card.records.length > 0
            model: card.records
            textRole: "name"
            currentIndex: card.selectedIndex()
            displayText: currentIndex >= 0 ? card.label(card.records[currentIndex]) : card.t(card.kind === "election" ? "select_election" : card.kind === "constituency" ? "select_constituency" : "candidates")
            Accessible.name: card.t(card.plural)
            enabled: !card.editorState.busy
            delegate: ItemDelegate {
                width: recordPicker.width
                required property var modelData
                required property int index
                text: card.label(modelData)
                highlighted: recordPicker.highlightedIndex === index
                contentItem: Text {
                    text: parent.text
                    textFormat: Text.PlainText
                    color: "#25344b"
                    elide: Text.ElideRight
                    verticalAlignment: Text.AlignVCenter
                }
            }
            onActivated: card.choose(card.kind, card.records[currentIndex].id)
            onActiveFocusChanged: if (activeFocus) Qt.callLater(function() { card.reveal(recordPicker) })
        }
        TextCaption {
            visible: card.parentReady && card.records.length === 0
            text: card.t(card.kind === "election" ? "no_saved_elections" : card.kind === "constituency" ? "no_constituencies" : "no_candidates")
        }
        ColumnLayout {
            visible: card.editing
            Layout.fillWidth: true
            spacing: 10
            RowLayout {
                Layout.fillWidth: true
                TextCaption { text: card.selected.id ? card.t("draft") + " · " + card.t("revision") + " " + card.selected.revision + (card.editorState.dirty[card.kind] ? " •" : "") : card.t("editing_new") }
                Action { text: card.t("reload_saved"); flat: true; visible: !!card.selected.id; onClicked: card.choose(card.kind, card.selected.id) }
            }
            TextCaption { text: card.t(card.nameKey) }
            Input {
                objectName: card.kind + "Name"
                text: card.form.name
                Accessible.name: card.t(card.nameKey)
                onTextEdited: card.config.setField(card.kind, "name", text)
            }
            TextCaption { visible: card.kind === "constituency"; text: card.t("constituency_code") }
            Input {
                visible: card.kind === "constituency"
                objectName: "constituencyCode"
                text: card.form.code || ""
                Accessible.name: card.t("constituency_code")
                onTextEdited: card.config.setField(card.kind, "code", text)
            }
            TextCaption { visible: card.kind === "candidate"; text: card.t("ballot_number") }
            Input {
                visible: card.kind === "candidate"
                objectName: "ballotNumber"
                text: card.form.ballot_number || ""
                inputMethodHints: Qt.ImhDigitsOnly
                Accessible.name: card.t("ballot_number")
                onTextEdited: card.config.setField(card.kind, "ballot_number", text)
            }
            TextCaption { visible: card.kind === "constituency"; text: card.t("one_seat_rule"); font.pixelSize: 12 }
            Action {
                text: card.t(card.editorState.busy ? "saving" : card.saveKey)
                highlighted: true
                Layout.fillWidth: true
                Layout.topMargin: 6
                enabled: !card.editorState.busy && (!card.selected.id || card.editorState.dirty[card.kind])
                onClicked: card.config.save(card.kind)
            }
        }
    }
}
