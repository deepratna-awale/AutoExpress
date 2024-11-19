/*
 * Created by David Adams
 * https://codeshack.io/multi-select-dropdown-html-javascript/
 * 
 * Released under the MIT license
 */
class MultiSelect {

    constructor(element, options = {}) {
        let defaults = {
            placeholder: 'Select item(s)',
            max: null,
            search: true,
            selectAll: false,
            listAll: true,
            closeListOnItemSelect: false,
            name: '',
            width: '95%',
            height: '',
            dropdownWidth: '90%',
            dropdownHeight: '',
            data: [],
            onChange: function () { },
            onSelect: function () { },
            onUnselect: function () { }
        };
        // Use a new object to avoid modifying defaults
        this.options = Object.assign({}, defaults, options);
        this.selectElement = typeof element === 'string' ? document.querySelector(element) : element;

        for (const prop in this.selectElement.dataset) {
            if (this.options[prop] !== undefined) {
                this.options[prop] = this.selectElement.dataset[prop];
            }
        }
        this.name = this.selectElement.getAttribute('name') ? this.selectElement.getAttribute('name') : 'multi-select-' + Math.floor(Math.random() * 1000000);
        if (!this.options.data.length) {
            let options = this.selectElement.querySelectorAll('option');
            for (let i = 0; i < options.length; i++) {
                this.options.data.push({
                    value: options[i].value,
                    text: options[i].innerHTML,
                    selected: options[i].selected,
                    html: options[i].getAttribute('data-html')
                });
            }
        }
        this.element = this._template();
        this.selectElement.replaceWith(this.element);
        this._updateSelected();
        this._eventHandlers();
    }

    _template() {
        let optionsHTML = '';
        for (let i = 0; i < this.data.length; i++) {
            optionsHTML += `
                <div class="multi-select-option${this.selectedValues.includes(this.data[i].value) ? ' multi-select-selected' : ''}" data-value="${this.data[i].value}">
                    <span class="multi-select-option-radio"></span>
                    <span class="multi-select-option-text">${this.data[i].html ? this.data[i].html : this.data[i].text}</span>
                </div>
            `;
        }
        let selectAllHTML = '';
        if (this.options.selectAll === true || this.options.selectAll === 'true') {
            selectAllHTML = `<div class="multi-select-all">
                <span class="multi-select-option-radio"></span>
                <span class="multi-select-option-text">Select all</span>
            </div>`;
        }
        let template = `
            <div class="multi-select ${this.name}"${this.selectElement.id ? ' id="' + this.selectElement.id + '"' : ''} style="${this.width ? 'width:' + this.width + ';' : ''}${this.height ? 'height:' + this.height + ';' : ''}">
                ${this.selectedValues.map(value => `<input class="lora-input-list" type="hidden" name="${this.name}[]" value="${value}">`).join('')}
                <div class="multi-select-header" style="${this.width ? 'width:' + '80%' + ';' : ''}${this.height ? 'height:' + this.height + ';' : ''}">
                    <span class="multi-select-header-max">${this.options.max ? this.selectedValues.length + '/' + this.options.max : ''}</span>
                    <span class="multi-select-header-placeholder">${this.placeholder}</span>
                </div>
                <div class="multi-select-options" style="${this.options.dropdownWidth ? 'width:' + this.options.dropdownWidth + ';' : ''}${this.options.dropdownHeight ? 'height:' + this.options.dropdownHeight + ';' : ''}">
                    ${this.options.search === true || this.options.search === 'true' ? '<input type="text" class="multi-select-search" placeholder="Search...">' : ''}
                    ${selectAllHTML}
                    ${optionsHTML}
                </div>
            </div>
        `;
        let element = document.createElement('div');
        element.style.display = 'flex';
        element.style.minWidth = '80%';
        element.innerHTML = template;

        return element;
    }

    _eventHandlers() {
        let headerElement = this.element.querySelector('.multi-select-header');

        // Assign onSelect and onUnselect functions to update selections
        const updateSelection = () => {
            this._updateSelected();
        };

        // Move these outside the loop to avoid overwriting
        this.options.onSelect = updateSelection;
        this.options.onUnselect = updateSelection;

        this.element.querySelectorAll('.multi-select-option').forEach(option => {
            option.onclick = () => {
                let selected = true;
                if (!option.classList.contains('multi-select-selected')) {
                    if (this.options.max && this.selectedValues.length >= this.options.max) {
                        return;
                    }
                    option.classList.add('multi-select-selected');
                    this.element.querySelector('.multi-select').insertAdjacentHTML('afterbegin', `<input type="hidden" name="${this.name}[]" value="${option.dataset.value}">`);
                    this.data.filter(data => data.value == option.dataset.value)[0].selected = true;
                } else {
                    option.classList.remove('multi-select-selected');
                    this.element.querySelector(`input[value="${option.dataset.value}"]`).remove();
                    this.data.filter(data => data.value == option.dataset.value)[0].selected = false;
                    selected = false;
                }
                if (this.options.search === true || this.options.search === 'true') {
                    this.element.querySelector('.multi-select-search').value = '';
                }
                this.element.querySelectorAll('.multi-select-option').forEach(option => option.style.display = 'flex');
                if (this.options.closeListOnItemSelect === true || this.options.closeListOnItemSelect === 'true') {
                    headerElement.classList.remove('multi-select-header-active');
                }
                this.options.onChange(option.dataset.value, option.querySelector('.multi-select-option-text').innerHTML, option);
                if (selected) {
                    this.options.onSelect(option.dataset.value, option.querySelector('.multi-select-option-text').innerHTML, option);
                } else {
                    this.options.onUnselect(option.dataset.value, option.querySelector('.multi-select-option-text').innerHTML, option);
                }
            };
        });

        headerElement.onclick = () => headerElement.classList.toggle('multi-select-header-active');
        if (this.options.search === true || this.options.search === 'true') {
            let search = this.element.querySelector('.multi-select-search');
            search.oninput = () => {
                this.element.querySelectorAll('.multi-select-option').forEach(option => {
                    option.style.display = option.querySelector('.multi-select-option-text').innerHTML.toLowerCase().indexOf(search.value.toLowerCase()) > -1 ? 'flex' : 'none';
                });
            };
        }
        if (this.options.selectAll === true || this.options.selectAll === 'true') {
            let selectAllButton = this.element.querySelector('.multi-select-all');
            selectAllButton.onclick = () => {
                let allSelected = selectAllButton.classList.contains('multi-select-selected');
                this.element.querySelectorAll('.multi-select-option').forEach(option => {
                    let dataItem = this.data.find(data => data.value == option.dataset.value);
                    if (dataItem && ((allSelected && dataItem.selected) || (!allSelected && !dataItem.selected))) {
                        option.click();
                    }
                });
                selectAllButton.classList.toggle('multi-select-selected');
            };
        }
        if (this.selectElement.id && document.querySelector('label[for="' + this.selectElement.id + '"]')) {
            document.querySelector('label[for="' + this.selectElement.id + '"]').onclick = () => {
                headerElement.classList.toggle('multi-select-header-active');
            };
        }
        document.addEventListener('click', event => {
            if (!event.target.closest('.' + this.name) && !event.target.closest('label[for="' + this.selectElement.id + '"]')) {
                headerElement.classList.remove('multi-select-header-active');
            }
        });
    }

    /**
     * Updates the selected items in the header to reflect the current state of the selected items.
     */
    _updateSelected() {
        const headerElement = this.element.querySelector('.multi-select-header');
        headerElement.innerHTML = ''; // Clear previous selections

        if (this.selectedValues.length > 0) {
            this.selectedItems.forEach(item => {
                const row = document.createElement('div');
                row.className = 'multi-select-header-option-row';
                row.style.background = 'var(--font-color)';
                row.style.color = 'black';
                row.style.margin = '4px 0';
                row.style.padding = '4px 8px';
                row.style.display = 'flex';
                row.style.flexDirection = 'row';
                row.style.alignItems = 'center';
                row.style.borderRadius = '5px';
                row.style.width = '100%';
                row.style.overflow = 'hidden';

                const text = document.createElement('span');
                text.textContent = item.text;
                text.classList.add('lora-name');
                text.style.flex = '2'; // Ensures text takes up available space

                const loraStrengthSelector = document.createElement('input');
                loraStrengthSelector.type = 'number';
                loraStrengthSelector.classList.add('lora-strength');
                loraStrengthSelector.name = 'lora-strength';
                loraStrengthSelector.value = '0.8';
                loraStrengthSelector.step = '0.05';
                loraStrengthSelector.style.marginLeft = '8px';
                loraStrengthSelector.style.marginRight = '4px'; // Space between text and close icon
                loraStrengthSelector.style.width = '25px'; // Ensures a consistent width for the input

                const closeIcon = document.createElement('span');
                closeIcon.classList.add('icon-x');
                closeIcon.style.cursor = 'pointer';
                closeIcon.style.marginLeft = '8px'; // Adds space between loraStrengthSelector and icon
                closeIcon.onclick = () => {
                    const option = this.element.querySelector(`.multi-select-option[data-value="${item.value}"]`);
                    if (option) option.click();
                };

                row.appendChild(text);
                row.appendChild(loraStrengthSelector);
                row.appendChild(closeIcon);
                headerElement.appendChild(row);
            });
        } else {
            headerElement.textContent = this.placeholder;
        }
    }

    get selectedValues() {
        return this.data.filter(data => data.selected).map(data => data.value);
    }

    get selectedItems() {
        return this.data.filter(data => data.selected);
    }

    set data(value) {
        this.options.data = value;
    }

    get data() {
        return this.options.data;
    }

    set selectElement(value) {
        this.options.selectElement = value;
    }

    get selectElement() {
        return this.options.selectElement;
    }

    set element(value) {
        this.options.element = value;
    }

    get element() {
        return this.options.element;
    }

    set placeholder(value) {
        this.options.placeholder = value;
    }

    get placeholder() {
        return this.options.placeholder;
    }

    set name(value) {
        this.options.name = value;
    }

    get name() {
        return this.options.name;
    }

    set width(value) {
        this.options.width = value;
    }

    get width() {
        return this.options.width;
    }

    set height(value) {
        this.options.height = value;
    }

    get height() {
        return this.options.height;
    }

    addLoraWithStrength(name, strength) {
        // Find the LoRA item
        let dataItem = this.data.find(item => item.text === name);
        if (!dataItem) {
            console.log('LoRA not found:', name);
            return;
        }

        // Mark the existing LoRA as selected
        dataItem.selected = true;
        const option = this.element.querySelector(`.multi-select-option[data-value="${dataItem.value}"]`);
        if (option && !option.classList.contains('multi-select-selected')) {
            option.classList.add('multi-select-selected');
        }

        // Update the selections
        this._updateSelected();

        // Set the strength value
        const strengthInput = this.element.querySelector(`.lora-strength[data-value="${dataItem.value}"]`);
        if (strengthInput) {
            strengthInput.value = strength;
        }
    }

}

document.querySelectorAll('multi-select').forEach(select => new MultiSelect(select));
