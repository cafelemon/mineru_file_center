(function () {
    const moveForm = document.querySelector("[data-files-move-form]");
    const checkboxes = Array.from(document.querySelectorAll("[data-file-checkbox]"));
    const selectAll = document.querySelector("[data-select-all]");
    const moveButton = document.querySelector("[data-move-button]");
    const selectionCounter = document.querySelector("[data-selection-counter]");
    const folderPickers = Array.from(document.querySelectorAll("[data-folder-picker]"));

    function escapeSelectorValue(value) {
        if (window.CSS && typeof window.CSS.escape === "function") {
            return window.CSS.escape(value);
        }
        return String(value).replace(/["\\]/g, "\\$&");
    }

    function updateSelectionState() {
        const selectedCount = checkboxes.filter((checkbox) => checkbox.checked).length;
        if (moveButton) {
            moveButton.disabled = selectedCount === 0;
        }
        if (selectionCounter) {
            selectionCounter.textContent = selectedCount
                ? "已选择 " + selectedCount + " 个文件"
                : "未选择文件";
        }
        if (selectAll) {
            selectAll.checked = selectedCount > 0 && selectedCount === checkboxes.length;
            selectAll.indeterminate = selectedCount > 0 && selectedCount < checkboxes.length;
        }
    }

    if (selectAll) {
        selectAll.addEventListener("change", function () {
            checkboxes.forEach((checkbox) => {
                checkbox.checked = selectAll.checked;
            });
            updateSelectionState();
        });
    }

    checkboxes.forEach((checkbox) => {
        checkbox.addEventListener("change", updateSelectionState);
    });

    if (moveForm) {
        moveForm.addEventListener("submit", function (event) {
            if (!checkboxes.some((checkbox) => checkbox.checked)) {
                event.preventDefault();
                updateSelectionState();
            }
        });
    }

    document.querySelectorAll("[data-folder-delete-form]").forEach((form) => {
        form.addEventListener("submit", function (event) {
            const folderPath = form.getAttribute("data-folder-path") || "该目录";
            if (!window.confirm("确认删除空目录：" + folderPath + "？")) {
                event.preventDefault();
            }
        });
    });

    document.querySelectorAll("[data-folder-rename-toggle]").forEach((button) => {
        button.addEventListener("click", function () {
            const folderPath = button.getAttribute("data-folder-path") || "";
            const panel = document.querySelector(
                '[data-folder-rename-panel][data-folder-path="' + escapeSelectorValue(folderPath) + '"]'
            );
            document.querySelectorAll("[data-folder-rename-panel]").forEach((item) => {
                if (item !== panel) {
                    item.hidden = true;
                }
            });
            if (!panel) {
                return;
            }
            panel.hidden = !panel.hidden;
            if (!panel.hidden) {
                const input = panel.querySelector('input[name="new_folder_name"]');
                if (input) {
                    input.focus();
                    input.select();
                }
            }
        });
    });

    folderPickers.forEach((picker) => {
        const trigger = picker.querySelector("[data-folder-picker-trigger]");
        const menu = picker.querySelector("[data-folder-picker-menu]");
        const input = picker.querySelector("[data-folder-picker-input]");
        const label = picker.querySelector("[data-folder-picker-label]");
        const choices = Array.from(picker.querySelectorAll("[data-folder-choice]"));

        function setOpen(isOpen) {
            if (!menu || !trigger) {
                return;
            }
            menu.hidden = !isOpen;
            trigger.setAttribute("aria-expanded", isOpen ? "true" : "false");
        }

        if (trigger) {
            trigger.addEventListener("click", function () {
                setOpen(menu ? menu.hidden : false);
            });
        }

        choices.forEach((choice) => {
            choice.addEventListener("click", function () {
                const folderPath = choice.getAttribute("data-folder-path") || "";
                const folderLabel = choice.getAttribute("data-folder-label") || "知识库根目录";
                if (input) {
                    input.value = folderPath;
                }
                if (label) {
                    label.textContent = folderLabel || "知识库根目录";
                }
                choices.forEach((item) => item.classList.remove("is-selected"));
                choice.classList.add("is-selected");
                setOpen(false);
            });
        });
    });

    document.addEventListener("click", function (event) {
        folderPickers.forEach((picker) => {
            if (!picker.contains(event.target)) {
                const menu = picker.querySelector("[data-folder-picker-menu]");
                const trigger = picker.querySelector("[data-folder-picker-trigger]");
                if (menu && trigger) {
                    menu.hidden = true;
                    trigger.setAttribute("aria-expanded", "false");
                }
            }
        });
    });

    document.addEventListener("keydown", function (event) {
        if (event.key !== "Escape") {
            return;
        }
        folderPickers.forEach((picker) => {
            const menu = picker.querySelector("[data-folder-picker-menu]");
            const trigger = picker.querySelector("[data-folder-picker-trigger]");
            if (menu && trigger) {
                menu.hidden = true;
                trigger.setAttribute("aria-expanded", "false");
            }
        });
        document.querySelectorAll("[data-folder-rename-panel]").forEach((panel) => {
            panel.hidden = true;
        });
    });

    updateSelectionState();
})();
