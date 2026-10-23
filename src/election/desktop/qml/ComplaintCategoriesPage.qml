pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: page
    required property var catalog
    required property var words
    property string locale: "tc"
    readonly property var editorState: catalog.state
    readonly property var selected: editorState.selected || ({})
    readonly property var form: editorState.form || ({})
    readonly property bool editable: editorState.editing && !editorState.busy
        && editorState.election.status !== "finalized"
    property string pendingAction: "reload"
    property int pendingId: 0
    signal reveal(var control)
    spacing: 20

    function t(key) { return words[key] || key }
    function label(row) { return row["label_" + locale] || row.label_en || "" }
    function indexOf(items, id) {
        for (let i = 0; i < items.length; i++) if (items[i].id === id) return i
        return -1
    }
    function restorePickers() {
        electionPicker.currentIndex = Qt.binding(function() {
            return page.indexOf(page.editorState.elections, page.editorState.election_id)
        })
        categoryPicker.currentIndex = Qt.binding(function() {
            return page.indexOf(page.editorState.items, page.selected.id)
        })
    }
    function choose(action, id) {
        let accepted = action === "election" ? catalog.selectElection(id, false)
            : action === "category" ? catalog.loadCategory(id, false) : catalog.reload(false)
        if (!accepted && editorState.dirty) {
            pendingAction = action
            pendingId = id
            discardDialog.open()
        }
        restorePickers()
    }

    component Heading: Label {
        textFormat: Text.PlainText
        color: "#25344b"
        font.pixelSize: 20
        font.weight: Font.Medium
        Layout.fillWidth: true
        wrapMode: Text.WordWrap
    }
    component Action: FormButton {
        id: action
        Layout.fillWidth: true
        implicitWidth: 160
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
    component Input: ColumnLayout {
        id: input
        required property string field
        required property string caption
        required property string controlName
        property bool immutable: false
        Layout.fillWidth: true
        spacing: 8
        FormCaption { text: input.caption }
        FormField {
            objectName: input.controlName
            text: page.form[input.field] || ""
            readOnly: !page.editable || input.immutable
            working: page.editorState.busy
            maximumLength: input.field === "code" ? 64 : 255
            Accessible.name: input.caption
            onTextEdited: page.catalog.setField(input.field, text)
            onReveal: control => page.reveal(control)
        }
    }
    component Picker: ComboBox {
        id: picker
        Layout.fillWidth: true
        enabled: !page.editorState.busy
        implicitHeight: Math.max(48, pickerText.implicitHeight + 24)
        contentItem: Text {
            id: pickerText
            text: picker.displayText
            textFormat: Text.PlainText
            font: picker.font
            color: "#25344b"
            wrapMode: Text.WordWrap
            verticalAlignment: Text.AlignVCenter
        }
        onActiveFocusChanged: if (activeFocus) Qt.callLater(function() {
            if (picker.activeFocus) page.reveal(picker)
        })
    }
    Connections {
        target: page.catalog
        function onStateChanged() { Qt.callLater(function() { page.restorePickers() }) }
    }

    RowLayout {
        Layout.fillWidth: true
        Heading { text: page.t("complaint_categories"); font.pixelSize: 28 }
        BusyIndicator {
            running: page.editorState.busy || page.editorState.refreshing
            visible: running
            implicitWidth: 28
            implicitHeight: 28
        }
        FormButton {
            objectName: "complaintCategoryRefresh"
            text: page.t("refresh")
            flat: true
            highlighted: false
            enabled: !page.editorState.busy && !page.editorState.refreshing
            onClicked: page.catalog.refresh()
            onReveal: control => page.reveal(control)
        }
    }
    FormCaption { text: page.t("complaint_categories_hint") }
    FormNotice {
        words: page.words
        error: page.editorState.error
        notice: page.editorState.notice
        onReveal: control => page.reveal(control)
    }
    FormCaption {
        visible: page.editorState.newer_revision
        text: page.t("complaint_category_newer")
        color: "#8a5c16"
    }
    FormPanel {
        implicitHeight: selection.implicitHeight + 40
        ColumnLayout {
            id: selection
            anchors.fill: parent
            anchors.margins: 20
            spacing: 12
            FormCaption { text: page.t("selected_election") }
            Picker {
                id: electionPicker
                objectName: "complaintCategoryElection"
                model: page.editorState.elections
                textRole: "name"
                currentIndex: page.indexOf(model, page.editorState.election_id)
                Accessible.name: page.t("selected_election")
                onActivated: index => {
                    if (index >= 0) page.choose("election", model[index].id)
                }
            }
            FormCaption {
                visible: !!page.editorState.election_id
                text: page.t(page.editorState.election.status || "draft")
            }
            FormCaption { text: page.t("complaint_category_select") }
            Picker {
                id: categoryPicker
                objectName: "complaintCategoryPicker"
                model: page.editorState.items
                currentIndex: page.indexOf(model, page.selected.id)
                displayText: currentIndex >= 0 ? model[currentIndex].code + " · "
                    + page.label(model[currentIndex]) : page.t("complaint_category_select")
                Accessible.name: page.t("complaint_category_select")
                delegate: ItemDelegate {
                    id: option
                    required property var modelData
                    required property int index
                    width: categoryPicker.width
                    highlighted: categoryPicker.highlightedIndex === index
                    implicitHeight: Math.max(48, optionText.implicitHeight + 20)
                    contentItem: Text {
                        id: optionText
                        text: option.modelData.code + " · " + page.label(option.modelData)
                            + (option.modelData.enabled ? "" : " · "
                                + page.t("complaint_category_disabled_label"))
                        textFormat: Text.PlainText
                        font: option.font
                        color: "#25344b"
                        wrapMode: Text.WordWrap
                    }
                }
                onActivated: index => {
                    if (index >= 0) page.choose("category", model[index].id)
                }
            }
            GridLayout {
                Layout.fillWidth: true
                columns: page.width > 750 ? 2 : 1
                columnSpacing: 12
                rowSpacing: 8
                Action {
                    objectName: "complaintCategoryNew"
                    text: page.t("complaint_category_new")
                    highlighted: false
                    enabled: !!page.editorState.election_id && !page.editorState.busy
                        && page.editorState.election.status !== "finalized"
                    onClicked: page.choose("category", 0)
                }
                Action {
                    objectName: "complaintCategoryReload"
                    text: page.t("reload_saved")
                    highlighted: false
                    enabled: !!page.editorState.election_id && !page.editorState.busy
                    onClicked: page.choose("reload", 0)
                }
            }
        }
    }
    FormPanel {
        visible: page.editorState.editing
        implicitHeight: editor.implicitHeight + 40
        ColumnLayout {
            id: editor
            anchors.fill: parent
            anchors.margins: 20
            spacing: 16
            Heading { text: page.t("complaint_category_select") }
            FormCaption {
                text: page.t("revision") + " " + (page.selected.revision || "—")
                    + (page.editorState.dirty ? " •" : "")
            }
            FormCaption {
                visible: page.editorState.election.status === "finalized"
                text: page.t("election_read_only")
            }
            Input {
                field: "code"; caption: page.t("complaint_category_code")
                controlName: "complaintCategoryCode"; immutable: !!page.selected.id
            }
            Input {
                field: "label_tc"; caption: page.t("complaint_category_tc")
                controlName: "complaintCategoryTc"
            }
            Input {
                field: "label_sc"; caption: page.t("complaint_category_sc")
                controlName: "complaintCategorySc"
            }
            Input {
                field: "label_en"; caption: page.t("complaint_category_en")
                controlName: "complaintCategoryEn"
            }
            CheckBox {
                id: enabledCheck
                objectName: "complaintCategoryEnabled"
                text: page.t("complaint_category_enabled")
                checked: !!page.form.enabled
                enabled: page.editable && !page.selected.is_other
                onClicked: page.catalog.setEnabled(checked)
                onActiveFocusChanged: if (activeFocus) Qt.callLater(function() {
                    if (enabledCheck.activeFocus) page.reveal(enabledCheck)
                })
            }
            CheckBox {
                id: descriptionCheck
                objectName: "complaintCategoryDescriptionRequired"
                text: page.t("complaint_description_rule")
                checked: !!page.form.description_required
                enabled: page.editable && !page.selected.is_other
                onClicked: page.catalog.setDescriptionRequired(checked)
                onActiveFocusChanged: if (activeFocus) Qt.callLater(function() {
                    if (descriptionCheck.activeFocus) page.reveal(descriptionCheck)
                })
            }
            FormCaption { visible: !!page.selected.is_other; text: page.t("complaint_other_note") }
            Heading { text: page.t("complaint_category_source"); font.pixelSize: 17 }
            FormCaption {
                text: page.t(page.selected.verified_source
                    ? "complaint_verified_reference" : "complaint_project_configured")
            }
            FormCaption {
                visible: !!page.selected.source_english
                text: page.selected.source_english || ""
            }
            FormCaption {
                visible: !!page.selected.reference_page
                text: page.t("complaint_reference_page") + " " + (page.selected.reference_page || "")
            }
            FormCaption { text: page.t("complaint_translation_note") }
            Action {
                objectName: "complaintCategorySave"
                text: page.t("complaint_category_save")
                working: page.editorState.busy
                enabled: page.editable && page.editorState.dirty && !page.editorState.newer_revision
                onClicked: page.catalog.save()
            }
        }
    }
    ConfirmationDialog {
        id: discardDialog
        title: page.t("discard_changes")
        message: page.t("unsaved_complaint_category_changes")
        acceptLabel: page.t("discard_changes")
        rejectLabel: page.t("keep_editing")
        onConfirmed: {
            if (page.pendingAction === "election") page.catalog.selectElection(page.pendingId, true)
            else if (page.pendingAction === "category") page.catalog.loadCategory(page.pendingId, true)
            else page.catalog.reload(true)
            page.restorePickers()
        }
    }
}
