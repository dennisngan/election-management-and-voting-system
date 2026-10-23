pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import QtCore

ColumnLayout {
    id: page
    required property var allocations
    required property var words
    property string locale: "tc"
    readonly property var editorState: allocations.state
    readonly property var form: editorState.forms || ({})
    readonly property var context: editorState.context || ({})
    readonly property var election: context.election || ({})
    readonly property var constituency: context.constituency || ({})
    readonly property var station: context.station || ({})
    readonly property var selected: editorState.selected || ({})
    readonly property bool hasSelected: !!selected.id
    readonly property bool canCreate: !!editorState.station_id
        && editorState.role === "polling_officer"
        && (election.status === "draft" || election.status === "active")
    readonly property bool canEdit: canCreate && !editorState.historical
    readonly property bool selectedReport: editorState.report_scope === "allocation_revision"
    readonly property bool reportAvailable: !!editorState.station_id && (!selectedReport || hasSelected)
    property string pendingAction: "allocation"
    property int pendingId: 0
    property string pendingFormat: "pdf"
    property string pendingLocale: "tc"
    signal reveal(var control)
    spacing: 20

    function t(key) { return words[key] || key }
    function counterLabel(row) { return (row.code || "") + " · " + (row.name || "") }
    function selectedIndex() {
        for (let i = 0; i < editorState.items.length; i++)
            if (editorState.items[i].id === selected.id) return i
        return -1
    }
    function counterIndex() {
        for (let i = 0; i < editorState.counters.length; i++)
            if (String(editorState.counters[i].id) === form.counter_id) return i
        return -1
    }
    function allocationLabel(row) {
        return t("allocation_record") + " " + row.id + " · " + counterLabel(row.counter)
            + " · " + row.series + " · " + t("revision") + " " + row.revision
            + " · " + row.quantity_display
    }
    function chooseAllocation(allocationId) {
        if (editorState.busy) return
        if (!allocations.loadAllocation(allocationId, false) && editorState.dirty) {
            pendingAction = "allocation"
            pendingId = allocationId
            discardDialog.open()
        }
    }
    function chooseRevision(revision) {
        if (editorState.busy) return
        if (!allocations.loadRevision(revision, false) && editorState.dirty) {
            pendingAction = "revision"
            pendingId = revision
            discardDialog.open()
        }
    }
    function moveFocus(control, forward) {
        let next = control.nextItemInFocusChain(forward)
        if (next) next.forceActiveFocus(forward ? Qt.TabFocusReason : Qt.BacktabFocusReason)
    }
    function languageName(code) {
        return code === "sc" ? "简体中文" : code === "en" ? "English" : "繁體中文"
    }
    function exportReport(format) {
        if (!reportAvailable || editorState.busy) return
        pendingFormat = format
        pendingLocale = locale
        exportDialog.nameFilters = format === "pdf" ? ["PDF (*.pdf)"] : ["CSV (*.csv)"]
        exportDialog.defaultSuffix = format
        let name = selectedReport ? "allocation-" + selected.id + "-r" + selected.revision
            : "station-" + editorState.station_id + "-current"
        exportDialog.selectedFile = exportDialog.currentFolder.toString() + "/p14-"
            + name + "-" + pendingLocale + "." + format
        exportDialog.open()
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

    RowLayout {
        Layout.fillWidth: true
        Heading {
            text: page.t("allocation_title")
            font.pixelSize: 28
        }
        BusyIndicator {
            running: page.editorState.busy || page.editorState.refreshing
            visible: running
            implicitWidth: 28
            implicitHeight: 28
            Accessible.name: page.t("loading")
        }
        FormButton {
            objectName: "allocationRefresh"
            text: page.t("refresh")
            flat: true
            highlighted: false
            working: page.editorState.busy || page.editorState.refreshing
            onClicked: page.allocations.refresh()
            onReveal: control => page.reveal(control)
        }
    }

    FormNotice {
        words: page.words
        error: page.editorState.error
        notice: page.editorState.notice
        onReveal: control => page.reveal(control)
    }
    FormNotice {
        words: page.words
        autoReveal: false
        notice: page.editorState.newer_revision ? "allocation_newer_revision" : ""
        onReveal: control => page.reveal(control)
    }

    FormPanel {
        implicitHeight: contextLayout.implicitHeight + 40
        ColumnLayout {
            id: contextLayout
            anchors.fill: parent
            anchors.margins: 20
            spacing: 8
            FormCaption {
                text: page.editorState.station_id ? page.election.name || "" : page.t("select_station")
                color: "#25344b"
                font.pixelSize: 18
                wrapMode: Text.Wrap
            }
            FormCaption {
                visible: !!page.editorState.station_id
                text: (page.constituency.code || "") + " · " + (page.constituency.name || "")
                    + "\n" + (page.station.code || "") + " · " + (page.station.name || "")
                wrapMode: Text.Wrap
            }
            FormCaption {
                visible: !!page.editorState.station_id
                text: page.t("role") + " · " + page.t(page.editorState.role || "") + "   "
                    + page.t("election_status") + " · " + page.t(page.election.status || "")
            }
            FormCaption {
                visible: !!page.editorState.station_id && !page.canEdit
                text: page.t(page.election.status === "finalized"
                    ? "election_read_only" : "allocation_read_only")
            }
            FormCaption {
                visible: !!page.editorState.station_id
                text: page.t("allocation_hint")
            }
        }
    }

    FormPanel {
        visible: !!page.editorState.station_id
        implicitHeight: availabilityLayout.implicitHeight + 40
        ColumnLayout {
            id: availabilityLayout
            anchors.fill: parent
            anchors.margins: 20
            spacing: 14
            Heading { text: page.t("allocation_availability") }
            FormCaption {
                visible: page.editorState.availability.length === 0
                text: page.t(page.editorState.refreshing ? "loading" : "allocation_no_stock")
            }
            Repeater {
                model: page.editorState.availability
                delegate: FormPanel {
                    id: balanceCard
                    required property var modelData
                    color: "#f7f9fd"
                    radius: 12
                    implicitHeight: balanceLayout.implicitHeight + 28
                    ColumnLayout {
                        id: balanceLayout
                        anchors.fill: parent
                        anchors.margins: 14
                        spacing: 10
                        FormCaption {
                            text: page.t("stock_series") + " · " + balanceCard.modelData.series
                            color: "#25344b"
                            font.pixelSize: 16
                            wrapMode: Text.Wrap
                        }
                        GridLayout {
                            Layout.fillWidth: true
                            columns: page.width > 740 ? 2 : 1
                            columnSpacing: 20
                            rowSpacing: 8
                            FormCaption {
                                text: page.t("allocation_received") + " · "
                                    + balanceCard.modelData.ordinary_received_display
                            }
                            FormCaption {
                                text: page.t("allocation_allocated") + " · "
                                    + balanceCard.modelData.allocated_display
                            }
                            FormCaption {
                                text: page.t("allocation_available") + " · "
                                    + balanceCard.modelData.available_display
                                color: "#25344b"
                            }
                            FormCaption {
                                text: page.t("stock_pool_replacement") + " · "
                                    + balanceCard.modelData.replacement_display
                            }
                            FormCaption {
                                text: page.t("stock_pool_tendered") + " · "
                                    + balanceCard.modelData.tendered_display
                            }
                        }
                        FormCaption {
                            visible: balanceCard.modelData.ranges.length === 0
                            text: page.t("allocation_no_stock")
                        }
                        Repeater {
                            model: balanceCard.modelData.ranges
                            delegate: FormCaption {
                                required property var modelData
                                text: page.t("stock_range") + " · " + modelData.serial_from
                                    + " – " + modelData.serial_to + " · "
                                    + page.t("stock_range_quantity") + " " + modelData.quantity_display
                                    + " · " + page.t("stock_receipt") + " " + modelData.receipt_id
                                    + " · " + page.t("revision") + " " + modelData.receipt_revision
                                wrapMode: Text.Wrap
                            }
                        }
                    }
                }
            }
        }
    }

    FormPanel {
        visible: !!page.editorState.station_id
        implicitHeight: pickerLayout.implicitHeight + 40
        ColumnLayout {
            id: pickerLayout
            anchors.fill: parent
            anchors.margins: 20
            spacing: 12
            FormCaption { text: page.t("allocation_records") }
            Action {
                objectName: "allocationNew"
                visible: page.canCreate
                text: page.t("allocation_new")
                flat: true
                highlighted: false
                working: page.editorState.busy
                onClicked: page.chooseAllocation(0)
            }
            ComboBox {
                id: allocationPicker
                objectName: "allocationPicker"
                visible: page.editorState.items.length > 0
                Layout.fillWidth: true
                enabled: !page.editorState.busy
                model: page.editorState.items
                currentIndex: page.selectedIndex()
                displayText: page.hasSelected
                    ? page.allocationLabel(page.selected) : page.t("allocation_select")
                Accessible.name: page.t("allocation_select")
                contentItem: Text {
                    text: allocationPicker.displayText
                    textFormat: Text.PlainText
                    color: "#25344b"
                    font: allocationPicker.font
                    elide: Text.ElideRight
                    verticalAlignment: Text.AlignVCenter
                }
                delegate: ItemDelegate {
                    id: allocationOption
                    required property var modelData
                    required property int index
                    width: allocationPicker.width
                    text: page.allocationLabel(modelData)
                    highlighted: allocationPicker.highlightedIndex === index
                    contentItem: Text {
                        text: allocationOption.text
                        textFormat: Text.PlainText
                        color: "#25344b"
                        font: allocationOption.font
                        wrapMode: Text.Wrap
                        verticalAlignment: Text.AlignVCenter
                    }
                }
                onActivated: index => {
                    if (index >= 0) page.chooseAllocation(model[index].id)
                    currentIndex = Qt.binding(function() { return page.selectedIndex() })
                }
                onActiveFocusChanged: if (activeFocus)
                    Qt.callLater(function() { if (allocationPicker.activeFocus) page.reveal(allocationPicker) })
            }
            FormCaption {
                visible: page.editorState.items.length === 0
                text: page.t(page.editorState.refreshing ? "loading" : "allocation_empty")
            }
        }
    }

    FormPanel {
        visible: !!page.editorState.station_id && (page.canEdit || page.hasSelected)
        implicitHeight: allocationForm.implicitHeight + 40
        ColumnLayout {
            id: allocationForm
            anchors.fill: parent
            anchors.margins: 20
            spacing: 14
            FormCaption {
                text: page.hasSelected
                    ? page.t(page.editorState.historical ? "stock_historical" : "stock_current")
                        + " · " + page.t("revision") + " " + page.selected.revision
                        + (page.editorState.dirty ? " •" : "")
                    : page.t("editing_new")
            }
            Action {
                objectName: "allocationReload"
                visible: page.hasSelected
                text: page.t(page.editorState.historical ? "stock_return_current" : "reload_saved")
                flat: true
                highlighted: false
                working: page.editorState.busy
                onClicked: page.chooseAllocation(page.selected.id)
            }
            GridLayout {
                Layout.fillWidth: true
                columns: page.width > 740 ? 2 : 1
                columnSpacing: 20
                rowSpacing: 12
                ColumnLayout {
                    Layout.fillWidth: true
                    FormCaption { text: page.t("allocation_counter") }
                    ComboBox {
                        id: counterPicker
                        objectName: "allocationCounter"
                        Layout.fillWidth: true
                        enabled: page.canEdit && !page.editorState.busy
                        model: page.editorState.counters
                        currentIndex: page.counterIndex()
                        displayText: page.hasSelected && !page.canEdit
                            ? page.counterLabel(page.selected.counter)
                            : currentIndex >= 0 ? page.counterLabel(model[currentIndex])
                                : page.t("allocation_counter")
                        Accessible.name: page.t("allocation_counter")
                        contentItem: Text {
                            text: counterPicker.displayText
                            textFormat: Text.PlainText
                            color: "#25344b"
                            font: counterPicker.font
                            elide: Text.ElideRight
                            verticalAlignment: Text.AlignVCenter
                        }
                        delegate: ItemDelegate {
                            id: counterOption
                            required property var modelData
                            required property int index
                            width: counterPicker.width
                            text: page.counterLabel(modelData)
                            highlighted: counterPicker.highlightedIndex === index
                            contentItem: Text {
                                text: counterOption.text
                                textFormat: Text.PlainText
                                color: "#25344b"
                                font: counterOption.font
                                wrapMode: Text.Wrap
                                verticalAlignment: Text.AlignVCenter
                            }
                        }
                        onActivated: index => {
                            if (index >= 0)
                                page.allocations.setField("counter_id", String(model[index].id))
                            currentIndex = Qt.binding(function() { return page.counterIndex() })
                        }
                        onActiveFocusChanged: if (activeFocus)
                            Qt.callLater(function() { if (counterPicker.activeFocus) page.reveal(counterPicker) })
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    FormCaption { text: page.t("stock_series") }
                    FormField {
                        objectName: "allocationSeries"
                        text: page.form.series || ""
                        maximumLength: 64
                        working: page.editorState.busy
                        readOnly: !page.canEdit
                        Accessible.name: page.t("stock_series")
                        onTextEdited: page.allocations.setField("series", text)
                        onReveal: control => page.reveal(control)
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    FormCaption { text: page.t("stock_serial_from") }
                    FormField {
                        objectName: "allocationSerialFrom"
                        text: page.form.serial_from || ""
                        maximumLength: 18
                        inputMethodHints: Qt.ImhDigitsOnly
                        working: page.editorState.busy
                        readOnly: !page.canEdit
                        Accessible.name: page.t("stock_serial_from")
                        onTextEdited: page.allocations.setField("serial_from", text)
                        onReveal: control => page.reveal(control)
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    FormCaption { text: page.t("stock_serial_to") }
                    FormField {
                        objectName: "allocationSerialTo"
                        text: page.form.serial_to || ""
                        maximumLength: 18
                        inputMethodHints: Qt.ImhDigitsOnly
                        working: page.editorState.busy
                        readOnly: !page.canEdit
                        Accessible.name: page.t("stock_serial_to")
                        onTextEdited: page.allocations.setField("serial_to", text)
                        onReveal: control => page.reveal(control)
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    FormCaption { text: page.t("allocation_event_at") }
                    FormField {
                        objectName: "allocationEventAt"
                        text: page.form.event_at || ""
                        placeholderText: "YYYY-MM-DD HH:mm[:ss[.ffffff]]"
                        maximumLength: 26
                        working: page.editorState.busy
                        readOnly: !page.canEdit
                        Accessible.name: page.t("allocation_event_at")
                        onTextEdited: page.allocations.setField("event_at", text)
                        onReveal: control => page.reveal(control)
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    FormCaption { text: page.t("allocation_quantity") }
                    FormField {
                        objectName: "allocationQuantity"
                        text: page.editorState.quantity_display || "—"
                        working: page.editorState.busy
                        readOnly: true
                        Accessible.name: page.t("allocation_quantity")
                        onReveal: control => page.reveal(control)
                    }
                }
            }
            FormCaption { text: page.t("allocation_time_hint") }
            FormCaption { text: page.t("stock_serial_hint") }
            FormCaption {
                visible: page.hasSelected && page.canEdit
                text: page.t("stock_correction_hint")
            }
            FormCaption {
                visible: page.hasSelected
                text: page.t("stock_reason")
            }
            TextArea {
                id: reasonInput
                objectName: "allocationReason"
                visible: page.hasSelected
                Layout.fillWidth: true
                implicitHeight: Math.max(92, contentHeight + topPadding + bottomPadding)
                text: page.canEdit ? page.form.reason || "" : page.selected.reason || ""
                textFormat: TextEdit.PlainText
                Keys.priority: Keys.BeforeItem
                Keys.onTabPressed: event => { page.moveFocus(reasonInput, true); event.accepted = true }
                Keys.onBacktabPressed: event => { page.moveFocus(reasonInput, false); event.accepted = true }
                clip: true
                wrapMode: TextEdit.WordWrap
                selectByMouse: true
                enabled: !page.editorState.busy
                readOnly: !page.canEdit
                leftPadding: 12
                rightPadding: 12
                topPadding: 12
                bottomPadding: 12
                topInset: 0
                Accessible.name: page.t("stock_reason")
                onTextEdited: page.allocations.setField("reason", text)
                onActiveFocusChanged: if (activeFocus)
                    Qt.callLater(function() { if (reasonInput.activeFocus) page.reveal(reasonInput) })
                background: Rectangle {
                    radius: 8
                    color: "white"
                    border.color: reasonInput.activeFocus ? "#1967d2" : "#a7b2c2"
                    border.width: reasonInput.activeFocus ? 2 : 1
                }
            }
            FormCaption {
                visible: page.hasSelected
                text: page.t("allocation_basis")
                color: "#25344b"
            }
            Repeater {
                model: page.selected.receipt_basis || []
                delegate: FormCaption {
                    required property var modelData
                    text: page.t("stock_receipt") + " " + modelData.receipt_id + " · "
                        + page.t("revision") + " " + modelData.revision + " · "
                        + page.t("stock_range") + " " + (modelData.range_line + 1)
                    wrapMode: Text.Wrap
                }
            }
            Action {
                objectName: "allocationSave"
                visible: page.canEdit
                text: page.t(page.editorState.busy ? "saving"
                    : page.hasSelected ? "stock_save_correction" : "allocation_save")
                working: page.editorState.busy
                enabled: !working && (!page.hasSelected || page.editorState.dirty)
                onClicked: page.allocations.save()
            }
        }
    }

    FormPanel {
        visible: page.hasSelected
        implicitHeight: historyLayout.implicitHeight + 40
        ColumnLayout {
            id: historyLayout
            anchors.fill: parent
            anchors.margins: 20
            spacing: 12
            Heading { text: page.t("allocation_history") }
            FormCaption {
                visible: page.editorState.history.length === 0
                text: page.t(page.editorState.busy ? "loading" : "allocation_no_history")
            }
            Repeater {
                model: page.editorState.history
                delegate: Action {
                    required property var modelData
                    objectName: "allocationHistoryRevision" + modelData.revision
                    text: page.t("revision") + " " + modelData.revision + " · "
                        + page.counterLabel(modelData.counter) + " · " + modelData.series
                        + " · " + modelData.serial_from + " – " + modelData.serial_to
                        + " · " + modelData.quantity_display + " · "
                        + page.allocations.formatTime(modelData.event_at)
                    flat: true
                    highlighted: false
                    working: page.editorState.busy
                    onClicked: page.chooseRevision(modelData.revision)
                }
            }
        }
    }

    FormPanel {
        visible: !!page.editorState.station_id
        implicitHeight: reportLayout.implicitHeight + 40
        ColumnLayout {
            id: reportLayout
            anchors.fill: parent
            anchors.margins: 20
            spacing: 12
            Heading { text: page.t("allocation_report") }
            FormCaption { text: page.t("allocation_report_hint") }
            FormCaption { text: page.t("allocation_report_scope") }
            ComboBox {
                id: reportScopePicker
                objectName: "allocationReportScope"
                Layout.fillWidth: true
                enabled: !page.editorState.busy
                model: [
                    { key: "station_current", label: page.t("allocation_report_station") },
                    { key: "allocation_revision", label: page.t("allocation_report_selected") }
                ]
                textRole: "label"
                currentIndex: page.selectedReport ? 1 : 0
                Accessible.name: page.t("allocation_report_scope")
                contentItem: Text {
                    text: reportScopePicker.currentText
                    textFormat: Text.PlainText
                    color: "#25344b"
                    font: reportScopePicker.font
                    elide: Text.ElideRight
                    verticalAlignment: Text.AlignVCenter
                }
                delegate: ItemDelegate {
                    id: reportScopeOption
                    required property var modelData
                    required property int index
                    width: reportScopePicker.width
                    text: modelData.label
                    highlighted: reportScopePicker.highlightedIndex === index
                    contentItem: Text {
                        text: reportScopeOption.text
                        textFormat: Text.PlainText
                        color: "#25344b"
                        font: reportScopeOption.font
                        wrapMode: Text.Wrap
                        verticalAlignment: Text.AlignVCenter
                    }
                }
                onActivated: index => {
                    if (index >= 0) page.allocations.setReportScope(model[index].key)
                    currentIndex = Qt.binding(function() { return page.selectedReport ? 1 : 0 })
                }
                onActiveFocusChanged: if (activeFocus)
                    Qt.callLater(function() { if (reportScopePicker.activeFocus) page.reveal(reportScopePicker) })
            }
            FormNotice {
                words: page.words
                autoReveal: false
                notice: page.selectedReport && !page.hasSelected ? "allocation_required" : ""
                onReveal: control => page.reveal(control)
            }
            FormCaption {
                text: page.t("stock_report_language") + " · " + page.languageName(page.locale)
                    + (page.selectedReport && page.hasSelected
                        ? "   " + page.t("revision") + " " + page.selected.revision : "")
            }
            GridLayout {
                Layout.fillWidth: true
                columns: page.width > 740 ? 2 : 1
                columnSpacing: 12
                rowSpacing: 8
                Action {
                    id: previewAction
                    objectName: "allocationPreview"
                    text: page.t("stock_preview")
                    working: page.editorState.busy
                    enabled: !working && page.reportAvailable
                    onClicked: page.allocations.preview(page.locale)
                }
                Action {
                    objectName: "allocationExportPdf"
                    text: page.t("stock_export_pdf")
                    working: page.editorState.busy
                    enabled: !working && page.reportAvailable
                    flat: true
                    highlighted: false
                    onClicked: page.exportReport("pdf")
                }
                Action {
                    objectName: "allocationExportCsv"
                    text: page.t("stock_export_csv")
                    working: page.editorState.busy
                    enabled: !working && page.reportAvailable
                    flat: true
                    highlighted: false
                    onClicked: page.exportReport("csv")
                }
            }
            FormCaption {
                visible: !!page.editorState.report_text
                text: page.t("stock_preview_language") + " · "
                    + page.languageName((page.editorState.report || ({})).locale || page.locale)
            }
            TextArea {
                id: reportText
                objectName: "allocationReportPreview"
                visible: !!page.editorState.report_text
                Layout.fillWidth: true
                implicitHeight: Math.max(120, contentHeight + topPadding + bottomPadding)
                readOnly: true
                selectByMouse: true
                text: page.editorState.report_text || ""
                textFormat: TextEdit.PlainText
                Keys.priority: Keys.BeforeItem
                Keys.onTabPressed: event => { page.moveFocus(reportText, true); event.accepted = true }
                Keys.onBacktabPressed: event => { page.moveFocus(reportText, false); event.accepted = true }
                Keys.onEscapePressed: event => {
                    previewAction.forceActiveFocus(Qt.OtherFocusReason)
                    event.accepted = true
                }
                clip: true
                wrapMode: TextEdit.WrapAnywhere
                Accessible.name: page.t("allocation_report")
                onActiveFocusChanged: if (activeFocus)
                    Qt.callLater(function() { if (reportText.activeFocus) page.reveal(reportText) })
            }
            FormCaption {
                objectName: "allocationExportPath"
                visible: !!page.editorState.export_path
                text: page.t("stock_export_location") + "\n" + (page.editorState.export_path || "")
                wrapMode: Text.WrapAnywhere
            }
        }
    }

    ConfirmationDialog {
        id: discardDialog
        title: page.t("discard_changes")
        message: page.t("unsaved_allocation_changes")
        acceptLabel: page.t("discard_changes")
        rejectLabel: page.t("keep_editing")
        onConfirmed: {
            if (page.pendingAction === "revision")
                page.allocations.loadRevision(page.pendingId, true)
            else page.allocations.loadAllocation(page.pendingId, true)
        }
    }
    FileDialog {
        id: exportDialog
        objectName: "allocationExportDialog"
        title: page.t(page.pendingFormat === "pdf" ? "stock_export_pdf" : "stock_export_csv")
        fileMode: FileDialog.SaveFile
        currentFolder: StandardPaths.writableLocation(StandardPaths.DocumentsLocation)
        onAccepted: page.allocations.download(page.pendingFormat, selectedFile.toString(), page.pendingLocale)
    }
}
