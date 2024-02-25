;
jQuery( function() {
    $("body").on('click','[data-stopPropagation]',function (e) {
        e.stopPropagation();
    });
    
    // 侧边栏
    $(document).on('click', '.pixels-aside-toggler', function() {
        $('.pixels-layout-sidebar').toggleClass('pixels-aside-open');
        $("body").toggleClass('pixels-layout-sidebar-close');
        
        if ($('.pixels-mask-modal').length == 0) {
            $('<div class="pixels-mask-modal"></div>').prependTo('body');
        } else {
            $( '.pixels-mask-modal' ).remove();
        }
    });
  
    // 遮罩层
    $(document).on('click', '.pixels-mask-modal', function() {
        $( this ).remove();
    	$('.pixels-layout-sidebar').toggleClass('pixels-aside-open');
        $('body').toggleClass('pixels-layout-sidebar-close');
    });
    
	// 侧边栏导航
    $(document).on('click', '.nav-item-has-subnav > a', function() {
		$subnavToggle = jQuery( this );
		$navHasSubnav = $subnavToggle.parent();
        $topHasSubNav = $subnavToggle.parents('.nav-item-has-subnav').last();
		$subnav       = $navHasSubnav.find('.nav-subnav').first();
        $viSubHeight  = $navHasSubnav.siblings().find('.nav-subnav:visible').outerHeight();
        $scrollBox    = $('.pixels-layout-sidebar-scroll');
		$navHasSubnav.siblings().find('.nav-subnav:visible').slideUp(500).parent().removeClass('open');
		$subnav.slideToggle( 300, function() {
			$navHasSubnav.toggleClass( 'open' );
			
			// 新增滚动条处理
			var scrollHeight  = 0;
			    pervTotal     = $topHasSubNav.prevAll().length,
			    boxHeight     = $scrollBox.outerHeight(),
		        innerHeight   = $('.sidebar-main').outerHeight(),
                thisScroll    = $scrollBox.scrollTop(),
                thisSubHeight = $(this).outerHeight(),
                footHeight    = 121;
			
			if (footHeight + innerHeight - boxHeight >= (pervTotal * 48)) {
			    scrollHeight = pervTotal * 48;
			}
            if ($subnavToggle.parents('.nav-item-has-subnav').length == 1) {
                $scrollBox.animate({scrollTop: scrollHeight}, 300);
            } else {
                // 子菜单操作
                if (typeof($viSubHeight) != 'undefined' && $viSubHeight != null) {
                    scrollHeight = thisScroll + thisSubHeight - $viSubHeight;
                    $scrollBox.animate({scrollTop: scrollHeight}, 300);
                } else {
                    if ((thisScroll + boxHeight - $scrollBox[0].scrollHeight) == 0) {
                        scrollHeight = thisScroll - thisSubHeight;
                        $scrollBox.animate({scrollTop: scrollHeight}, 300);
                    }
                }
            }
		});
	});
});

showSchemas = function getSchemas() {
    $.ajax({
        type: 'POST',
        url: '/api/metadata/get-schemas',
        contentType: 'application/json',
        data: JSON.stringify({}),
        success: function (response) {
            var schemaMenu = $('#schemaMenu');

            // Clear existing items
            schemaMenu.empty();

            if (Array.isArray(response.schemas) && response.schemas.length > 0) {
                response.schemas.forEach(function (schema) {
                    var listItem = $('<li class="nav-item nav-item-has-subnav"><a href="#" onclick="showTables(\'' + schema.name + '\')">' + schema.name + '</a><ul class="nav nav-subnav" id="' + schema.name + '"></ul></li>');
                    schemaMenu.append(listItem);
                });
            } else {
                // If no schemas, show an "empty" first-level menu
                var emptySchemaItem = $('<li><a href="#">empty</a></li>');
                schemaMenu.append(emptySchemaItem);
            }
        },
        error: function (error) {
            console.error('Error fetching schemas:', error);
        }
    });
}

// Define getTables function
showTables = function getTables(schema) {
    $.ajax({
        type: 'POST',
        url: '/api/metadata/get-tables',
        contentType: 'application/json',
        data: JSON.stringify({ "schemaName": schema }),
        success: function(response) {
            var tableMenu = $('#' + schema); // Use a unique ID for each schema's table menu

            // Clear existing items
            tableMenu.empty();
            if (Array.isArray(response.tables) && response.tables.length > 0) {
                response.tables.forEach(function(table) {
                    var listItem = $('<li class="nav-item nav-item-has-subnav"><a href="javascript:void(0)" onclick="showColumns(\'' + schema + '\', \'' + table.name + '\')">' + table.name + '</a><ul class="nav nav-subnav" id="' + schema + '_' + table.name + '"></ul></li>');
                    tableMenu.append(listItem);
                });
            } else {
                // If no tables, show an "empty" second-level menu
                var emptyTableItem = $('<li><a href="#">empty</a></li>');
                tableMenu.append(emptyTableItem);
            }
        },
        error: function(error) {
            console.error('Error fetching tables:', error);
        }
    });
}

// Define showColumns function
showColumns = function showColumns(schema, table) {
    $.ajax({
        type: 'POST',
        url: '/api/metadata/get-columns',
        contentType: 'application/json',
        data: JSON.stringify({ "schemaName": schema, "tableName": table }),
        success: function(response) {
            var columnMenu = $('#' + schema + '_' + table); // Use a unique ID for each table's column menu

            // Clear existing items
            columnMenu.empty();

            if (Array.isArray(response.columns) && response.columns.length > 0) {
                response.columns.forEach(function(column) {
                    var listItem = $('<li><a href="#">' + column.name + '</a></li>');
                    columnMenu.append(listItem);
                });
            } else {
                // If no columns, show an "empty" third-level menu
                var emptyColumnItem = $('<li><a href="#">empty</a></li>');
                columnMenu.append(emptyColumnItem);
            }
        },
        error: function(error) {
            console.error('Error fetching columns:', error);
        }
    });
}

document.addEventListener('DOMContentLoaded', function () {
    // Get the input field
    var chatInput = document.getElementById('chat-input');

    // Check if the element exists before adding the event listener
    if (chatInput) {
        // Add an event listener for the "keydown" event
        chatInput.addEventListener('keydown', function (event) {
            // Check if the pressed key is Enter (key code 13)
            if (event.keyCode === 13) {
                // Prevent the default form submission behavior
                event.preventDefault();

                // Call the function to send the query
                sendQuery();
            }
        });
    }
});

// 添加一个函数，用于在聊天区域显示用户输入的消息和执行结果
function sendQuery() {
    var chatInput = document.getElementById('chat-input').value;
    var executionHintSelect = document.getElementById('execution-hint-select').value;
    var outputRowsInput = document.getElementById('output-rows-input').value;
    var chatArea = document.getElementById('chat-area');

    // 创建一个新的消息元素，代表用户输入的消息
    var userMessageElement = document.createElement('div');
    userMessageElement.className = 'user-message';
    userMessageElement.textContent = chatInput;

    // 将新的消息元素添加到聊天区域
    chatArea.appendChild(userMessageElement);

    // 发送后端请求，执行查询
    executeQuery(chatInput, executionHintSelect, outputRowsInput, chatArea);
}

// 发送后端请求，执行查询
function executeQuery(query, executionHint, outputRows, chatArea) {
    // 构建SubmitQueryRequest对象
    var submitQueryRequest = {
        query: query,
        executionHint: executionHint,
        limitRows: outputRows,
    };

    // 发起submitQuery请求
    fetch('/api/query/submit-query', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(submitQueryRequest),
    })
        .then(response => response.json())
        .then(data => {
            // 恢复 query 默认值
            document.getElementById('chat-input').value = ""

            //  创建结果显示区域
            var systemMessage = document.createElement('div');
            systemMessage.className = 'system-message';

            //  创建状态显示区域
            var statusDisplay = document.createElement('div');
            statusDisplay.className = 'query-status';
            statusDisplay.textContent = 'Query Status: unknown\n';
            systemMessage.appendChild(statusDisplay);

            //  创建结果显示区域
            var resultDisplay = document.createElement('div');
            resultDisplay.className = 'query-results';
            resultDisplay.style.display = 'none'; //  默认隐藏结果
            systemMessage.appendChild(resultDisplay);

            //  将新的结果显示区域添加到聊天区域
            document.getElementById('chat-area').appendChild(systemMessage);

            //  如果查询成功，继续处理
            if (data.errorCode === 0) {
                //  显示查询状态
                updateQueryStatusAndResults(data.traceToken, statusDisplay, resultDisplay);
            } else {
                //  如果查询失败，显示错误消息
                resultDisplay.textContent = 'Error: ' + data.errorMessage;
            }
        })
        .catch(error => {
            console.error('Error:', error);
            // 在出错时更新结果显示区域
            resultDisplay.textContent = 'Error occurred during query execution.';
        });
}

// 更新查询状态和结果
function updateQueryStatusAndResults(traceToken, statusDisplay, resultDisplay) {
    // 更新查询状态
    updateQueryStatus(traceToken, function (status) {
        // 显示查询状态
        statusDisplay.textContent = 'Query Status: ' + status + '\n';

        // 如果查询状态为 "finished"，获取结果并更新显示
        if (status.toLowerCase() === 'finished') {
            //   添加折叠/展开按钮
            var toggleResults = document.createElement('span');
            toggleResults.className = 'toggle-results';
            toggleResults.addEventListener('click', function () {
                if (resultDisplay.style.display === 'none') {
                    resultDisplay.style.display = 'block';
                    toggleResults.classList.add('expanded');
                } else {
                    resultDisplay.style.display = 'none';
                    toggleResults.classList.remove('expanded');
                }
            });

            //  将折叠按钮添加到状态显示区域
            statusDisplay.appendChild(toggleResults);

            getQueryResult(traceToken, function (result) {
                // 显示查询结果
                displayQueryResult(result, resultDisplay);
            });
        }
    });
}

// 更新查询状态
function updateQueryStatus(traceToken, callback) {
    // 定义标志，判断是否继续刷新状态
    var shouldRefresh = true;

    // 定时刷新查询状态
    var refreshInterval = setInterval(function () {
        if (shouldRefresh) {
            // 构造GetQueryStatusRequest
            var getRequest = {
                traceTokens: [traceToken]
            };

            // 发送请求到后端
            fetch('/api/query/get-query-status', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(getRequest),
            })
                .then(response => response.json())
                .then(data => {
                    // 处理后端返回的查询状态
                    if (data.errorCode === 0) {
                        var status = data.queryStatuses[traceToken];

                        // 执行回调函数，传递查询状态
                        if (typeof callback === 'function') {
                            callback(status);
                        }

                        // 如果查询状态为 "finished"，停止刷新
                        if (status.toLowerCase() === 'finished') {
                            shouldRefresh = false;
                            clearInterval(refreshInterval);
                        }
                    } else {
                        console.error('Error getting query status:', data.errorMessage);
                        shouldRefresh = false;
                        clearInterval(refreshInterval);
                    }
                })
                .catch(error => {
                    console.error('Error updating query status:', error);
                    shouldRefresh = false;
                    clearInterval(refreshInterval);
                });
        }
    }, 500); // 每0.5秒刷新一次，根据需求调整
}

// 获取查询结果
function getQueryResult(traceToken, callback) {
    // 发起getQueryResult请求
    fetch('/api/query/get-query-result', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ traceToken: traceToken }),
    })
        .then(response => response.json())
        .then(result => {
            // 执行回调函数，传递查询结果
            if (typeof callback === 'function') {
                callback(result);
            }
        })
        .catch(error => {
            console.error('Error getting query result:', error);
        });
}

// 修改显示查询结果的函数，保留第一行的状态信息
function displayQueryResult(result, resultDisplay) {
    // 获取显示结果的DOM元素
    var resultDisplayContent = document.createElement('div');

    // 处理成功的情况
    var columnNames = result.columnNames;
    var rows = result.rows;
    var columnPrintSizes = result.columnPrintSizes;

    // 创建表格元素
    var table = document.createElement('table');

    // 创建表头
    var thead = document.createElement('thead');
    var headerRow = document.createElement('tr');

    columnNames.forEach(function (columnName, index) {
        var columnPrintSize = columnPrintSizes[index] || columnName.length + 2;
        var th = document.createElement('th');
        th.textContent = columnName;
        th.style.width = columnPrintSize + 3 + 'ch'; // 增加固定长度
        headerRow.appendChild(th);
    });

    thead.appendChild(headerRow);
    table.appendChild(thead);

    // 创建表体
    var tbody = document.createElement('tbody');

    rows.forEach(function (row) {
        var tr = document.createElement('tr');

        columnNames.forEach(function (_, index) {
            var td = document.createElement('td');
            var value = row[index];
            if (value === undefined || value === null) {
                value = 'null';
            }
            td.textContent = value;
            tr.appendChild(td);
        });

        tbody.appendChild(tr);
    });

    table.appendChild(tbody);
    resultDisplayContent.appendChild(table);

    // 将新的结果显示区域添加到已有的结果显示区域
    resultDisplay.appendChild(resultDisplayContent);
}
